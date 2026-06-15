"""Databricks REST API helpers for Unity Catalog table management and external metadata.

Covers:
- Printing HTTP responses for debugging
- SQL identifier and string quoting utilities
- External metadata CRUD via the lineage-tracking API
- Updating Unity Catalog table properties via the SQL Statements API

Environment variables (loaded from .env):
    DATABRICKS_HOST: Base URL of the Databricks workspace.
    TOKEN: Personal access token for authentication.
    EXTERNAL_METADATA_NAME: Name of the external metadata object.
    EXTERNAL_METADATA_SYSTEM_TYPE: System type (e.g. "DATABRICKS").
    EXTERNAL_METADATA_ENTITY_TYPE: Entity type (e.g. "TABLE").
    DATABRICKS_WAREHOUSE_ID: SQL warehouse ID used to run statements.
    DATABRICKS_TABLE_FULL_NAME: Fully qualified table name (catalog.schema.table).
"""

import os
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv("./.env")

HOST = os.getenv("DATABRICKS_HOST", "https://dbc-de078d0d-b410.cloud.databricks.com")
TOKEN = os.environ["TOKEN"]

EXTERNAL_METADATA_NAME = os.getenv("EXTERNAL_METADATA_NAME", "system_table_metadata_test")
EXTERNAL_METADATA_SYSTEM_TYPE = os.getenv("EXTERNAL_METADATA_SYSTEM_TYPE", "DATABRICKS")
EXTERNAL_METADATA_ENTITY_TYPE = os.getenv("EXTERNAL_METADATA_ENTITY_TYPE", "TABLE")
SQL_WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "ecd5b0f5bd2dabb3")
TABLE_FULL_NAME = os.getenv("DATABRICKS_TABLE_FULL_NAME", "workspace.default.ingestion_events")

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}


def print_response(label: str, response: requests.Response) -> None:
    """Print the HTTP status code and body of a response for debugging.

    Args:
        label: A human-readable label prepended to the status line.
        response: The HTTP response object returned by the requests library.
    """
    print(f"{label}: {response.status_code}")
    try:
        print(response.json())
    except ValueError:
        print(response.text)


def quote_identifier(identifier: str) -> str:
    """Backtick-quote a dot-separated Unity Catalog identifier.

    Each part is escaped so that backticks inside part names are doubled,
    then the parts are rejoined with dots.

    Args:
        identifier: A dot-separated identifier such as "catalog.schema.table".

    Returns:
        A fully quoted identifier, e.g. "`catalog`.`schema`.`table`".
    """
    return ".".join(f"`{part.replace('`', '``')}`" for part in identifier.split("."))


def quote_sql_string(value: Any) -> str:
    """Single-quote a value for use as a SQL string literal.

    Single quotes inside the value are escaped by doubling them.

    Args:
        value: The value to quote. Converted to str before quoting.

    Returns:
        A SQL-safe single-quoted string literal, e.g. "'my value'".
    """
    return "'" + str(value).replace("'", "''") + "'"


def list_external_metadata() -> None:
    """List all external metadata objects registered in the workspace.

    Calls GET /api/2.0/lineage-tracking/external-metadata and prints
    the result. Raises an HTTPError if the request fails.

    Raises:
        requests.HTTPError: If the API returns a non-2xx status code.
    """
    response = requests.get(
        f"{HOST}/api/2.0/lineage-tracking/external-metadata",
        headers=headers,
        timeout=30,
    )
    print_response("list external metadata", response)
    response.raise_for_status()


def create_external_metadata() -> None:
    """Create an external metadata object for lineage tracking.

    Uses the values of EXTERNAL_METADATA_NAME, EXTERNAL_METADATA_SYSTEM_TYPE,
    and EXTERNAL_METADATA_ENTITY_TYPE module-level constants. Prints the API
    response and raises on HTTP error.

    Raises:
        requests.HTTPError: If the API returns a non-2xx status code.
    """
    response = requests.post(
        f"{HOST}/api/2.0/lineage-tracking/external-metadata",
        headers=headers,
        json={
            "name": EXTERNAL_METADATA_NAME,
            "system_type": EXTERNAL_METADATA_SYSTEM_TYPE,
            "entity_type": EXTERNAL_METADATA_ENTITY_TYPE,
            "description": "Test external metadata object created through the REST API.",
            "url": f"{HOST}/explore/data/system/information_schema/tables",
            "columns": [
                "table_catalog",
                "table_schema",
                "table_name",
                "table_type",
            ],
            "properties": {
                "source_catalog": "system",
                "source_schema": "information_schema",
                "source_table": "tables",
                "owner_team": "data_platform",
            },
        },
        timeout=30,
    )
    print_response("create external metadata", response)
    response.raise_for_status()


def update_table_properties_with_sql(
    table_full_name: str,
    properties: dict[str, str],
) -> dict[str, Any]:
    """Set one or more TBLPROPERTIES on a Unity Catalog table via SQL.

    Builds and submits an ALTER TABLE ... SET TBLPROPERTIES statement
    through the SQL Statements API using the configured warehouse.

    Args:
        table_full_name: Fully qualified table name (catalog.schema.table).
        properties: Key-value pairs to set as table properties.

    Returns:
        The parsed JSON response from the SQL Statements API.

    Raises:
        ValueError: If DATABRICKS_WAREHOUSE_ID is not configured.
        requests.HTTPError: If the API returns a non-2xx status code.
    """
    if not SQL_WAREHOUSE_ID:
        raise ValueError("Set DATABRICKS_WAREHOUSE_ID in .env before running SQL statements.")

    property_sql = ",\n            ".join(
        f"{quote_sql_string(key)} = {quote_sql_string(value)}"
        for key, value in properties.items()
    )
    statement = f"""
        ALTER TABLE {quote_identifier(table_full_name)}
        SET TBLPROPERTIES (
            {property_sql}
        )
    """

    response = requests.post(
        f"{HOST}/api/2.0/sql/statements",
        headers=headers,
        json={
            "warehouse_id": SQL_WAREHOUSE_ID,
            "statement": statement,
            "wait_timeout": "30s",
        },
        timeout=60,
    )
    print_response("update table properties with SQL", response)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    # create_external_metadata()
    # list_external_metadata()
    update_table_properties_with_sql(
        TABLE_FULL_NAME,
        {
            "dih.domain": "payments",
            "dih.sensitivity": "internal",
            "dih.owner_team": "data_engineering",
        },
    )
