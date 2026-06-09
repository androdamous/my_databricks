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



if __name__ == "__main__":
    with Path("./views/dummy_view.yml").open("r", encoding="utf-8") as file:
        view_contract = file.read()
    
    with Path("./views/child_dummy_view.yml").open("r", encoding="utf-8") as file:
        child_view_contract = file.read()

    view_contract_sql = generate_view_creation_sql("workspace.default.dummy_view_as_code", view_contract)
    child_view_contract_sql = generate_view_creation_sql("workspace.default.child_dummy_view_as_code", child_view_contract)

    send_sql_statement(view_contract_sql)
    send_sql_statement(child_view_contract_sql)
