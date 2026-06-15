"""View-as-code deployment for Databricks metric views.

Reads YAML view definitions from the ``views/`` directory and deploys each one
to Unity Catalog as a metric view using ``CREATE OR REPLACE VIEW ... WITH METRICS
LANGUAGE YAML``.

All view files are processed in parallel (pool of 4 workers). Because of this,
dependency order between views is not guaranteed — deploy views that depend on
other views in a separate step after their upstream sources exist.

Environment variables (via to_catalog_deployment):
    TOKEN: Personal access token for authentication.
    DATABRICKS_HOST or HOST: Base URL of the Databricks workspace.
    DATABRICKS_WAREHOUSE_ID or WAREHOUSE_UID: SQL warehouse used to run statements.
"""

from pathlib import Path
from typing import Optional

from to_catalog_deployment import send_sql_statement

VIEW_CREATION_SQL = """
CREATE OR REPLACE VIEW {} WITH METRICS LANGUAGE YAML AS
$$
{}
$$
"""


def generate_view_creation_sql(view_name: str, yaml_content: str) -> str:
    """Wrap a YAML metric view definition in a ``CREATE OR REPLACE VIEW`` statement.

    Args:
        view_name: Fully qualified view name (e.g. ``workspace.default.my_view``).
        yaml_content: Raw YAML string containing the metric view definition.

    Returns:
        A complete SQL statement ready for submission to a Databricks warehouse.
    """
    return VIEW_CREATION_SQL.format(view_name, yaml_content)


def process_view_contract(view_contract_path: str, trace_uid: Optional[str] = None) -> None:
    """Deploy a single YAML view contract to Unity Catalog.

    Reads the YAML file at ``view_contract_path``, derives the view name from
    the file stem, builds a ``CREATE OR REPLACE VIEW`` SQL statement, and submits
    it to the configured Databricks SQL warehouse.

    The deployed view is registered under ``workspace.default.<stem>``, where
    ``<stem>`` is the filename without extension.

    Args:
        view_contract_path: Path to the ``.yml`` view definition file.
        trace_uid: Optional trace identifier for logging/debugging purposes.
    """
    print(
        f"Processing view contract: {view_contract_path} with trace UID: {trace_uid}")
    with Path(view_contract_path).open("r", encoding="utf-8") as file:
        view_contract = file.read()

    view_name = Path(view_contract_path).stem
    view_contract_sql = generate_view_creation_sql(
        f"workspace.default.{view_name}", view_contract)
    send_sql_statement(view_contract_sql)


def process_all_view_contracts(contracts_directory: str) -> None:
    """Deploy all YAML view contracts found in a directory, in parallel.

    Globs for ``*.yml`` files in ``contracts_directory`` and processes each one
    concurrently using a pool of 4 worker processes. Prints a summary on start
    and completion.

    Args:
        contracts_directory: Path to the directory containing ``.yml`` view files.
    """
    contract_paths = []
    for contract_file in Path(contracts_directory).glob("*.yml"):
        contract_paths.append(contract_file)
    import multiprocessing
    print(f"Found {len(contract_paths)} view contracts to process.")
    with multiprocessing.Pool(4) as pool:
        pool.map(process_view_contract, contract_paths)
    print("Finished processing all view contracts.")


if __name__ == "__main__":
    contracts_directory = "./views"
    process_all_view_contracts(contracts_directory)
