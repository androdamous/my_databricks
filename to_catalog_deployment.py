"""Catalog deployment utilities for Unity Catalog tables.

Provides:
- SQL statement submission and polling via the Databricks SQL Statements API
- YAML contract parsing for table definitions
- DDL generation (CREATE TABLE / ALTER TABLE) from parsed contracts
- Idempotent contract apply (create if absent, update metadata if present)

Environment variables (loaded from .env):
    TOKEN: Personal access token for authentication.
    DATABRICKS_HOST or HOST: Base URL of the Databricks workspace.
    DATABRICKS_WAREHOUSE_ID or WAREHOUSE_UID: SQL warehouse used to run statements.
"""

import os
import time
from pathlib import Path
from typing import Any

import requests
import yaml
from dotenv import load_dotenv


load_dotenv(".env")

TOKEN = os.environ.get("TOKEN", "")
HOST = os.environ.get("DATABRICKS_HOST") or os.environ.get("HOST", "")
WAREHOUSE_UID = os.environ.get(
    "DATABRICKS_WAREHOUSE_ID") or os.environ.get("WAREHOUSE_UID", "")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

TYPE_MAPPING: dict[str, str] = {
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


def send_sql_statement(
    sql: str,
    wait_timeout: str = "30s",
    poll_interval_seconds: int = 2,
    max_wait_seconds: int = 120,
) -> dict[str, Any]:
    """Submit a SQL statement to a Databricks SQL warehouse and wait for completion.

    The statement is submitted with ``on_wait_timeout=CONTINUE`` so the API
    returns immediately if execution exceeds ``wait_timeout``. This function
    then polls until the statement reaches a terminal state.

    Args:
        sql: The SQL statement to execute.
        wait_timeout: Server-side timeout passed to the API (e.g. "30s").
        poll_interval_seconds: Seconds to sleep between polling requests.
        max_wait_seconds: Hard client-side timeout before raising TimeoutError.

    Returns:
        The final parsed JSON response from the SQL Statements API.

    Raises:
        ValueError: If HOST, WAREHOUSE_UID, or TOKEN are not configured.
        RuntimeError: If the statement ends in FAILED, CANCELED, or CLOSED state,
            or if the initial response does not include a statement_id.
        TimeoutError: If the statement does not finish within ``max_wait_seconds``.
        requests.HTTPError: If any HTTP request returns a non-2xx status code.
    """
    if not HOST:
        raise ValueError("Set DATABRICKS_HOST or HOST in .env.")
    if not WAREHOUSE_UID:
        raise ValueError(
            "Set DATABRICKS_WAREHOUSE_ID or WAREHOUSE_UID in .env.")
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
            raise RuntimeError(error.get("message")
                               or f"SQL statement ended with state {state}.")
        if not statement_id:
            raise RuntimeError(
                f"SQL response did not include statement_id: {statement_response}")
        if time.monotonic() - started_at > max_wait_seconds:
            raise TimeoutError(
                f"SQL statement {statement_id} did not finish within {max_wait_seconds}s.")

        time.sleep(poll_interval_seconds)
        response = requests.get(
            f"{HOST}/api/2.0/sql/statements/{statement_id}",
            headers=HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        statement_response = response.json()


def parse_contract(contract_path: str = "dummy_contract/assets/dummy_table.yaml") -> dict[str, Any]:
    """Parse and validate a YAML table contract file.

    The contract must contain a ``table`` object with at minimum:
    - ``name``: the table name
    - ``source.location.catalog``: target catalog
    - ``source.location.schema``: target schema
    - ``columns``: a non-empty list of ``{name, type}`` objects

    Args:
        contract_path: Path to the YAML contract file.

    Returns:
        The fully parsed contract as a nested dictionary.

    Raises:
        ValueError: If the contract is missing required fields or is structurally invalid.
    """
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


def to_databricks_sql_ddl(contract: dict[str, Any], mode: str = "create") -> str | list[str]:
    """Generate Databricks SQL DDL from a parsed table contract.

    Args:
        contract: A parsed contract dictionary as returned by :func:`parse_contract`.
        mode: ``"create"`` to produce a ``CREATE TABLE IF NOT EXISTS`` statement
            (returns a single string), or ``"update"`` to produce a list of
            ``COMMENT ON TABLE`` / ``ALTER TABLE ... ALTER COLUMN ... COMMENT``
            statements (returns a list of strings).

    Returns:
        A single DDL string when ``mode="create"``, or a list of SQL strings
        when ``mode="update"``.

    Raises:
        ValueError: If ``mode`` is not ``"create"`` or ``"update"``.
    """
    table = contract["table"]
    location = table["source"]["location"]

    def qid(value): return f"`{str(value).replace('`', '``')}`"
    def qstr(value): return "'" + str(value).replace("'", "''") + "'"
    def dtype(value): return TYPE_MAPPING.get(
        str(value).lower(), str(value).upper())

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
            statements.append(
                f"COMMENT ON TABLE {full_table_name} IS {qstr(table['description'])}")

        for column in table["columns"]:
            if column.get("description"):
                statements.append(
                    f"ALTER TABLE {full_table_name} ALTER COLUMN {qid(column['name'])} "
                    f"COMMENT {qstr(column['description'])}"
                )
            if column.get("tags"):
                statements.append(
                    f"ALTER TABLE {full_table_name} ALTER COLUMN {qid(column['name'])} "
                    f"SET TAGS ({"".join([f"{qstr(tag_key)} = {qstr(tag_value)}" for tag_key,
                                          tag_value in column.get("tags").items()])})"
                )

        return statements

    raise ValueError("mode must be create or update.")


def update_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply a table contract to Unity Catalog idempotently.

    Checks whether the target table already exists in the catalog's
    ``information_schema``. If it does not exist, creates it with
    :func:`to_databricks_sql_ddl` in ``"create"`` mode. If it already
    exists, applies column and table-level comment updates in ``"update"`` mode.

    Args:
        contract: A parsed contract dictionary as returned by :func:`parse_contract`.

    Returns:
        A list of SQL statement response dictionaries from :func:`send_sql_statement`.
    """
    table = contract["table"]
    location = table["source"]["location"]
    def qid(value): return f"`{str(value).replace('`', '``')}`"
    def qstr(value): return "'" + str(value).replace("'", "''") + "'"

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
    # contract = parse_contract()
    # print(to_databricks_sql_ddl(contract, mode="update"))
