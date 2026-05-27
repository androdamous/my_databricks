import os

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


def print_response(label, response):
    print(f"{label}: {response.status_code}")
    try:
        print(response.json())
    except ValueError:
        print(response.text)


def quote_identifier(identifier):
    return ".".join(f"`{part.replace('`', '``')}`" for part in identifier.split("."))


def quote_sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def list_external_metadata():
    response = requests.get(
        f"{HOST}/api/2.0/lineage-tracking/external-metadata",
        headers=headers,
        timeout=30,
    )
    print_response("list external metadata", response)
    response.raise_for_status()


def create_external_metadata():
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


def update_table_properties_with_sql(table_full_name, properties):
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
