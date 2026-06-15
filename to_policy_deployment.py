from collections import defaultdict
from pathlib import Path
import time
import yaml

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import (
    ColumnMaskOptions,
    FunctionArgument,
    MatchColumn,
    PolicyInfo,
    PolicyType,
    SecurableType,
)
from databricks.sdk.service.sql import StatementState
from databricks.sdk.service.tags import TagPolicy, Value

MASKING_FUNCTION_MAPPING = {
    "labelling": ColumnMaskOptions(
        function_name="workspace.default.labelling_mask",
        on_column="sensitive_data",
        using=[FunctionArgument(constant="4")],
    ),
}

MASKING_FUNCTION_DDL = {
    "workspace.default.labelling_mask": """
CREATE OR REPLACE FUNCTION workspace.default.labelling_mask(value STRING, mask_count STRING)
RETURNS STRING
LANGUAGE SQL
RETURN REPEAT('0', TRY_CAST(mask_count AS INT))
"""
}

SECURABLE_TYPE_MAPPING = {
    "schema": SecurableType.SCHEMA,
    "table": SecurableType.TABLE,
    "catalog": SecurableType.CATALOG,
}

POLICY_TYPE_MAPPING = {
    "column_mask": PolicyType.POLICY_TYPE_COLUMN_MASK,
    "row_filter": PolicyType.POLICY_TYPE_ROW_FILTER,
}


def ensure_tag_policies(w: WorkspaceClient, raw_policies: list[dict]) -> None:
    """Register tag keys as governed tags so they can be used in ABAC conditions."""
    tag_values: dict[str, set[str]] = defaultdict(set)
    for policy in raw_policies:
        for condition in policy.get("conditions", []):
            tag_values[condition["tag_key"]].add(condition["tag_value"])

    existing = {tp.tag_key: tp for tp in w.tag_policies.list_tag_policies()}

    for tag_key, values in tag_values.items():
        tag_policy = TagPolicy(
            tag_key=tag_key,
            values=[Value(name=v) for v in sorted(values)],
        )
        if tag_key in existing:
            w.tag_policies.update_tag_policy(
                tag_key=tag_key,
                tag_policy=tag_policy,
                update_mask="values",
            )
            print(f"Updated tag policy: {tag_key}")
        else:
            w.tag_policies.create_tag_policy(tag_policy)
            print(f"Created tag policy: {tag_key}")

    # Poll until all tag keys are visible to the policy engine
    required = set(tag_values.keys())
    for attempt in range(10):
        visible = {tp.tag_key for tp in w.tag_policies.list_tag_policies()}
        if required.issubset(visible):
            break
        print(f"Waiting for tag policies to propagate ({attempt + 1}/10)...")
        time.sleep(3)


def ensure_masking_function(w: WorkspaceClient, function_name: str) -> None:
    ddl = MASKING_FUNCTION_DDL.get(function_name)
    if not ddl:
        return
    warehouses = list(w.warehouses.list())
    if not warehouses:
        raise RuntimeError("No SQL warehouses available.")
    warehouse_id = warehouses[0].id
    response = w.statement_execution.execute_statement(
        statement=ddl.strip(),
        warehouse_id=warehouse_id,
        wait_timeout="30s",
    )
    if response.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(
            f"Failed to create function {function_name}: {response.status.error}"
        )
    print(f"Function ensured: {function_name}")


def parse_policies(file_path: str = "./dummy_contract/policies/dummy_policy.yaml") -> tuple[list[dict], list[PolicyInfo]]:
    def qstr(value): return "'" + str(value).replace("'", "''") + "'"
    with Path(file_path).open("r", encoding="utf-8") as file:
        policy_contract = yaml.safe_load(file)

    raw_policies = policy_contract.get("policies", [])
    policy_infos = []
    for policy in raw_policies:
        policy_infos.append(PolicyInfo(
            name=policy.get("name"),
            comment=policy.get("description"),
            on_securable_type=SECURABLE_TYPE_MAPPING.get(policy.get("on_securable_object", {}).get("type")),
            on_securable_fullname=policy.get("on_securable_object", {}).get("name"),
            for_securable_type=SecurableType.TABLE,
            policy_type=POLICY_TYPE_MAPPING.get(policy.get("type")),
            to_principals=[principal.get("name") for principal in policy.get("to_principals", [])],
            except_principals=policy.get("except_principals", []),
            match_columns=[
                MatchColumn(
                    condition=f"has_tag_value({qstr(condition.get('tag_key'))}, {qstr(condition.get('tag_value'))})",
                    alias=condition.get("alias")
                ) for condition in policy.get("conditions", [])
            ],
            column_mask=MASKING_FUNCTION_MAPPING.get(policy.get("function"))
        ))

    return raw_policies, policy_infos


def upsert_policy(w: WorkspaceClient, policy_info: PolicyInfo) -> None:
    securable_type = policy_info.on_securable_type.value.lower()
    securable_fullname = policy_info.on_securable_fullname

    existing = {
        p.name: p
        for p in w.policies.list_policies(
            on_securable_type=securable_type,
            on_securable_fullname=securable_fullname,
        )
    }

    if policy_info.name in existing:
        w.policies.update_policy(
            on_securable_type=securable_type,
            on_securable_fullname=securable_fullname,
            name=policy_info.name,
            policy_info=policy_info,
        )
        print(f"Updated policy: {policy_info.name}")
    else:
        w.policies.create_policy(policy_info)
        print(f"Created policy: {policy_info.name}")


if __name__ == "__main__":
    w = WorkspaceClient()

    raw_policies, policy_infos = parse_policies()

    # Step 1: register governed tag keys used in conditions
    ensure_tag_policies(w, raw_policies)

    # Step 2: ensure masking functions exist
    for col_mask in MASKING_FUNCTION_MAPPING.values():
        ensure_masking_function(w, col_mask.function_name)

    # Step 3: deploy policies
    for policy_info in policy_infos:
        upsert_policy(w, policy_info)
