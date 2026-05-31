# Databricks API Experiments

Small Python scripts for testing Databricks REST APIs against a Unity Catalog
workspace.

## Setup

Install dependencies:

```bash
pip install requests python-dotenv
```

Create a local `.env` file:

```env
TOKEN=your_databricks_pat
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_WAREHOUSE_ID=your_sql_warehouse_id
DATABRICKS_TABLE_FULL_NAME=workspace.default.ingestion_events
```

`.env` is ignored by git because it contains secrets.

## Main Script

Run:

```bash
python databricks_api.py
```
   
The current `__main__` block updates table properties through the Databricks SQL
Statements API:

```sql
ALTER TABLE `workspace`.`default`.`ingestion_events`
SET TBLPROPERTIES (...)
```

This is implemented by:

```python
update_table_properties_with_sql(table_full_name, properties)
```

Use this for normal Unity Catalog tables where your principal has permission to
alter table metadata.

## External Metadata API

`databricks_api.py` also includes helpers for Databricks external metadata:

```python
create_external_metadata()
list_external_metadata()
```

These call:

```text
POST /api/2.0/lineage-tracking/external-metadata
GET  /api/2.0/lineage-tracking/external-metadata
```

External metadata objects are lineage-tracking securables. They do not create
Unity Catalog tables and do not appear as normal tables in Catalog Explorer.

Required privilege:

```text
CREATE EXTERNAL METADATA on the metastore
```

## Notes

- Databricks `system.*` tables are read-only. You can query them, but you cannot
  update their table properties directly.
- To attach custom metadata to system-table information, create your own table
  or external metadata object and join/reference it separately.
- The Unity Catalog Tables create endpoint accepts `data_source_format` only for
  external Delta table creation. Do not send `data_source_format` for managed
  table creation.
