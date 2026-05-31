import os
import time
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv


load_dotenv(".env")

TOKEN = os.environ.get("TOKEN", "")
HOST = os.environ.get("DATABRICKS_HOST") or os.environ.get("HOST", "")
WAREHOUSE_UID = os.environ.get("DATABRICKS_WAREHOUSE_ID") or os.environ.get("WAREHOUSE_UID", "")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

TYPE_MAPPING = {
    "integer": "INT",
    "int": "INT",
    "string": "STRING",
    "boolean": "BOOLEAN",
    "bool": "BOOLEAN",
    "float": "FLOAT",
    "double": "DOUBLE",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "long": "BIGINT",
    "bigint": "BIGINT",
    "delta": "DELTA",
}


def send_sql_statement(sql, wait_timeout="30s", poll_interval_seconds=2, max_wait_seconds=120):
    if not HOST:
        raise ValueError("Set DATABRICKS_HOST or HOST in .env.")
    if not WAREHOUSE_UID:
        raise ValueError("Set DATABRICKS_WAREHOUSE_ID or WAREHOUSE_UID in .env.")
    if not TOKEN:
        raise ValueError("Set TOKEN in .env.")

    response = requests.post(
        f"{HOST}/api/2.0/sql/statements",
        headers=HEADERS,
        json={
            "warehouse_id": WAREHOUSE_UID,
            "statement": sql,
            "wait_timeout": wait_timeout,
            "on_wait_timeout": "CONTINUE",
        },
        timeout=60,
    )
    response.raise_for_status()
    statement_response = response.json()
    statement_id = statement_response.get("statement_id")
    started_at = time.monotonic()

    while True:
        status = statement_response.get("status", {})
        state = status.get("state")

        if state == "SUCCEEDED":
            return statement_response
        if state in {"FAILED", "CANCELED", "CLOSED"}:
            error = status.get("error", {})
            raise RuntimeError(error.get("message") or f"SQL statement ended with state {state}.")
        if not statement_id:
            raise RuntimeError(f"SQL response did not include statement_id: {statement_response}")
        if time.monotonic() - started_at > max_wait_seconds:
            raise TimeoutError(f"SQL statement {statement_id} did not finish within {max_wait_seconds}s.")

        time.sleep(poll_interval_seconds)
        response = requests.get(
            f"{HOST}/api/2.0/sql/statements/{statement_id}",
            headers=HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        statement_response = response.json()


def parse_contract(contract_path="dummy_contract/assets/dummy_table.yaml"):
    with Path(contract_path).open("r", encoding="utf-8") as file:
        contract = yaml.safe_load(file)

    table = contract.get("table") if isinstance(contract, dict) else None
    if not isinstance(table, dict):
        raise ValueError("Contract must contain a table object.")
    if not table.get("name"):
        raise ValueError("Missing table.name.")
    if not table.get("source", {}).get("location", {}).get("catalog"):
        raise ValueError("Missing table.source.location.catalog.")
    if not table.get("source", {}).get("location", {}).get("schema"):
        raise ValueError("Missing table.source.location.schema.")
    if not isinstance(table.get("columns"), list) or not table["columns"]:
        raise ValueError("table.columns must be a non-empty list.")
    for column in table["columns"]:
        if not isinstance(column, dict) or not column.get("name") or not column.get("type"):
            raise ValueError("Each column must contain name and type.")

    return contract


def to_databricks_sql_ddl(contract, mode="create"):
    table = contract["table"]
    location = table["source"]["location"]

    qid = lambda value: f"`{str(value).replace('`', '``')}`"
    qstr = lambda value: "'" + str(value).replace("'", "''") + "'"
    dtype = lambda value: TYPE_MAPPING.get(str(value).lower(), str(value).upper())

    full_table_name = ".".join(
        [qid(location["catalog"]), qid(location["schema"]), qid(table["name"])]
    )

    if mode == "create":
        column_lines = []
        for column in table["columns"]:
            column_sql = f"{qid(column['name'])} {dtype(column['type'])}"
            if column.get("description"):
                column_sql += f" COMMENT {qstr(column['description'])}"
            column_lines.append(column_sql)

        ddl = f"CREATE TABLE IF NOT EXISTS {full_table_name} (\n    "
        ddl += ",\n    ".join(column_lines)
        ddl += "\n)"

        if table.get("type"):
            ddl += f"\nUSING {dtype(table['type'])}"
        if table.get("description"):
            ddl += f"\nCOMMENT {qstr(table['description'])}"
        return ddl

    if mode == "update":
        statements = []
        if table.get("description"):
            statements.append(f"COMMENT ON TABLE {full_table_name} IS {qstr(table['description'])}")

        for column in table["columns"]:
            if column.get("description"):
                statements.append(
                    f"ALTER TABLE {full_table_name} ALTER COLUMN {qid(column['name'])} "
                    f"COMMENT {qstr(column['description'])}"
                )
        return statements

    raise ValueError("mode must be create or update.")


def update_contract(contract):
    table = contract["table"]
    location = table["source"]["location"]
    qid = lambda value: f"`{str(value).replace('`', '``')}`"
    qstr = lambda value: "'" + str(value).replace("'", "''") + "'"

    table_exists_sql = f"""
        SELECT 1
        FROM {qid(location["catalog"])}.information_schema.tables
        WHERE table_schema = {qstr(location["schema"])}
          AND table_name = {qstr(table["name"])}
        LIMIT 1
    """
    table_exists_response = send_sql_statement(table_exists_sql)
    rows = table_exists_response.get("result", {}).get("data_array") or []

    if not rows:
        return [send_sql_statement(to_databricks_sql_ddl(contract, mode="create"))]

    return [
        send_sql_statement(statement)
        for statement in to_databricks_sql_ddl(contract, mode="update")
    ]


if __name__ == "__main__":
    update_contract(parse_contract())
