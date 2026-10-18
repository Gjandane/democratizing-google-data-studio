import pytest
from dss.harness.nodes.plan import DerivedField, Join
from dss.harness.nodes.view import select_sql, expression

SOURCE = {"bq_table": "project.data.sales", "columns": [
    {"name": "date", "bq_type": "DATE"}, {"name": "revenue", "bq_type": "FLOAT"}]}


def test_base_and_derived_golden():
    fields = [DerivedField(name="tax", sql="`t0`.`revenue` * 0.1", type="FLOAT"),
              DerivedField(name="net", sql="`t0`.`revenue` * 0.9", type="FLOAT")]
    assert select_sql([SOURCE], fields, []) == (
        "SELECT\n  `t0`.`date` AS `date`,\n  `t0`.`revenue` AS `revenue`,\n"
        "  `t0`.`revenue` * 0.1 AS `tax`,\n  `t0`.`revenue` * 0.9 AS `net`\n"
        "FROM `project.data.sales` AS `t0`")


def test_join_golden():
    other = {"bq_table": "project.data.regions", "columns": [{"name": "date"}, {"name": "group"}]}
    assert select_sql([SOURCE, other], [], [Join(table=other["bq_table"], on="`t0`.`date` = `t1`.`date`")]) == (
        "SELECT\n  `t0`.`date` AS `date`,\n  `t0`.`revenue` AS `revenue`,\n"
        "  `t1`.`group` AS `group`\nFROM `project.data.sales` AS `t0`\n"
        "LEFT JOIN `project.data.regions` AS `t1` ON `t0`.`date` = `t1`.`date`")


def test_date_like_golden():
    source = {"bq_table": "project.data.sales", "columns": [{"name": "date", "bq_type": "STRING", "date_like": True}]}
    assert select_sql([source], [], []) == (
        "SELECT\n  COALESCE(SAFE.PARSE_DATE('%Y-%m-%d', `t0`.`date`), "
        "SAFE.PARSE_DATE('%m/%d/%Y', `t0`.`date`), SAFE.PARSE_DATE('%Y/%m/%d', `t0`.`date`), "
        "SAFE.PARSE_DATE('%d-%b-%Y', `t0`.`date`)) AS `date`\nFROM `project.data.sales` AS `t0`")


def test_existing_bigquery_column_names():
    source = {"bq_table": "project.data.sales", "columns": [{"name": "OrderDate"}, {"name": "_id"}, {"name": "Order Total"}]}
    assert select_sql([source], [], []) == (
        "SELECT\n  `t0`.`OrderDate` AS `orderdate`,\n  `t0`.`_id` AS `id`,\n"
        "  `t0`.`Order Total` AS `order_total`\nFROM `project.data.sales` AS `t0`")


def test_expressions_quote_identifiers_and_allow_literal_keywords():
    assert expression("IF(t0.status = 'UPDATE', t0.`select`, 0)") == "IF(`t0`.`status` = 'UPDATE', `t0`.`select`, 0)"
    assert expression("t0.date") == "`t0`.`date`"


@pytest.mark.parametrize("sql", [
    "TIMESTAMP_ADD(`t0`.`ts`, INTERVAL 1 MINUTE)",
    "EXTRACT(DAYOFWEEK FROM `t0`.`ts`)",
    r"REGEXP_EXTRACT(`t0`.`value`, r'\d+')",
    "CAST(b'hello' AS STRING)",
    "JSON_VALUE(JSON '{\"x\":1}', '$.x')",
    "TO_HEX(CAST(`t0`.`value` AS BYTES))"])
def test_expression_preserves_sql_syntax(sql):
    assert expression(sql) == sql


@pytest.mark.parametrize("sql", ["1; DROP TABLE x", "(SELECT 1)", "1 -- comment"])
def test_reject_statements(sql):
    with pytest.raises(ValueError):
        select_sql([SOURCE], [DerivedField(name="extra", sql=sql, type="INTEGER")], [])


def test_reject_duplicate_and_unknown_join():
    with pytest.raises(ValueError, match="unique"):
        select_sql([SOURCE], [DerivedField(name="date", sql="1", type="INTEGER")], [])
    with pytest.raises(ValueError, match="connected"):
        select_sql([SOURCE], [], [Join(table="project.data.unknown", on="TRUE")])
