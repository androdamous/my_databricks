
from pathlib import Path

from to_catalog_deployment import send_sql_statement

VIEW_CREATION_SQL = """
CREATE OR REPLACE VIEW {} WITH METRICS LANGUAGE YAML AS
$$
{}
$$
"""


def generate_view_creation_sql(view_name, yaml_content):
    return VIEW_CREATION_SQL.format(view_name, yaml_content)


def process_view_contract(view_contract_path, trace_uid=None):
    print(
        f"Processing view contract: {view_contract_path} with trace UID: {trace_uid}")
    with Path(view_contract_path).open("r", encoding="utf-8") as file:
        view_contract = file.read()

    view_name = Path(view_contract_path).stem
    view_contract_sql = generate_view_creation_sql(
        f"workspace.default.{view_name}", view_contract)
    send_sql_statement(view_contract_sql)


def process_all_view_contracts(contracts_directory):
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
