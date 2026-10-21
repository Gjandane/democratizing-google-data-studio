import pytest
from dss.harness.nodes.view import DerivedField, Join
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


from dss.artifacts.models import DerivedField as ArtifactField, ViewSources
from dss.harness.nodes.view import blueprint_sql, blueprint_fields


UNION_SOURCES = [
    {'id': 's_sales', 'bq_table': 'project.data.sales', 'columns': [
        {'name': 'order', 'bq_type': 'INTEGER'}, {'name': 'date', 'bq_type': 'DATE'}]},
    {'id': 's_groups', 'bq_table': 'project.data.groups', 'columns': [
        {'name': 'order', 'bq_type': 'INTEGER'}, {'name': 'group', 'bq_type': 'STRING'}]}]


def test_blueprint_union_golden_nulls_provenance_reserved_words():
    selection = ViewSources(base='s_sales', joins=[], union=['s_groups'])
    assert blueprint_sql(UNION_SOURCES, selection, []) == (
        "SELECT\n  `t0`.`order` AS `order`,\n  `t0`.`date` AS `date`,\n"
        "  CAST(NULL AS STRING) AS `group`,\n  's_sales' AS `dataset_name`\n"
        "FROM `project.data.sales` AS `t0`\nUNION ALL\n"
        "SELECT\n  `t1`.`order` AS `order`,\n  CAST(NULL AS DATE) AS `date`,\n"
        "  `t1`.`group` AS `group`,\n  's_groups' AS `dataset_name`\n"
        "FROM `project.data.groups` AS `t1`")
    assert blueprint_fields(UNION_SOURCES, selection, []) == [
        {'name': 'order', 'type': 'INT64', 'role': 'metric'},
        {'name': 'date', 'type': 'DATE', 'role': 'dimension'},
        {'name': 'group', 'type': 'STRING', 'role': 'dimension'},
        {'name': 'dataset_name', 'type': 'STRING', 'role': 'dimension'}]


def test_blueprint_structured_join_golden():
    selection = ViewSources(base='s_sales', joins=[{'source_id': 's_groups', 'on': [
        {'left': 'order', 'right': 'order'}]}], union=[])
    assert blueprint_sql(UNION_SOURCES, selection, []) == (
        "SELECT\n  `t0`.`order` AS `order`,\n  `t0`.`date` AS `date`,\n"
        "  `t1`.`group` AS `group`\nFROM `project.data.sales` AS `t0`\n"
        "LEFT JOIN `project.data.groups` AS `t1` ON `t0`.`order` = `t1`.`order`")


def test_blueprint_union_scalar_derived_after_normalization():
    selection = ViewSources(base='s_sales', joins=[], union=['s_groups'])
    derived = ArtifactField(name='filtered_order', expression="IF(`group` = 'VIP', `order`, NULL)",
                            type='number', description='Only VIP orders')
    sql = blueprint_sql(UNION_SOURCES, selection, [derived])
    assert sql.startswith("SELECT\n  `order`,\n  `date`,\n  `group`,\n  `dataset_name`,\n  IF(`group` = 'VIP', `order`, NULL) AS `filtered_order`\nFROM (\n")
    assert sql.endswith(') AS `base`') and sql.count('UNION ALL') == 1
    assert 'WHERE' not in sql


@pytest.mark.parametrize('expression', ['SUM(`order`)', 'COUNTIF(`order` > 1)', 'ROW_NUMBER() OVER ()', '(SELECT 1)'])
def test_blueprint_rejects_non_scalar_derivations(expression):
    with pytest.raises(ValueError):
        blueprint_sql(UNION_SOURCES, ViewSources(base='s_sales', joins=[], union=[]), [
            ArtifactField(name='unsafe', expression=expression, type='number', description='')])


def test_union_numeric_widening_and_type_conflict():
    from copy import deepcopy
    sources = deepcopy(UNION_SOURCES)
    selection = ViewSources(base='s_sales', joins=[], union=['s_groups'])
    sources[1]['columns'][0]['bq_type'] = 'FLOAT'
    assert 'CAST(`t0`.`order` AS FLOAT64) AS `order`' in blueprint_sql(sources, selection, [])
    sources[1]['columns'][0]['bq_type'] = 'STRING'
    with pytest.raises(ValueError, match='compatible types'):
        blueprint_sql(sources, selection, [])


@pytest.mark.parametrize('selection', [
    {'base': 'unknown', 'joins': [], 'union': []},
    {'base': 's_sales', 'joins': [], 'union': ['s_sales']},
    {'base': 's_sales', 'joins': [{'source_id': 's_groups', 'on': []}], 'union': []},
    {'base': 's_sales', 'joins': [{'source_id': 's_groups', 'on': [{'left': 'missing', 'right': 'group'}]}], 'union': []}])
def test_blueprint_invalid_sources_or_keys(selection):
    with pytest.raises(ValueError):
        blueprint_sql(UNION_SOURCES, ViewSources.model_validate(selection), [])


def test_union_date_like_null_type_and_normalized_headers():
    sources = [{'id': 's_a', 'bq_table': 'project.data.a', 'columns': [
        {'name': 'Order Date', 'bq_type': 'STRING', 'date_like': True}]},
        {'id': 's_b', 'bq_table': 'project.data.b', 'columns': [{'name': 'Order Total', 'bq_type': 'FLOAT'}]}]
    sql = blueprint_sql(sources, ViewSources(base='s_a', joins=[], union=['s_b']), [])
    assert "SAFE.PARSE_DATE('%Y-%m-%d', `t0`.`Order Date`)" in sql
    assert 'CAST(NULL AS DATE) AS `order_date`' in sql
    assert 'CAST(NULL AS FLOAT64) AS `order_total`' in sql


def test_confirmed_context_derivations_keep_raw_scope_before_normalization():
    sources = [{'id': 's_base', 'bq_table': 'project.data.raw', 'columns': [
        {'name': 'Order Total', 'bq_type': 'FLOAT'},
        {'name': 'order_date', 'bq_type': 'STRING', 'date_like': True}]}]
    fields = [ArtifactField(name='tax', expression='t0.`Order Total` * 0.1', type='number', description=''),
        ArtifactField(name='parsed', expression="PARSE_DATE('%m/%d/%Y', order_date)", type='date', description='')]
    sql = blueprint_sql(sources, ViewSources(base='s_base', joins=[], union=[]), fields,
                        context_fields=['tax', 'parsed'])
    assert sql == ("SELECT\n  `t0`.`Order Total` AS `order_total`,\n  "
        "COALESCE(SAFE.PARSE_DATE('%Y-%m-%d', `t0`.`order_date`), "
        "SAFE.PARSE_DATE('%m/%d/%Y', `t0`.`order_date`), "
        "SAFE.PARSE_DATE('%Y/%m/%d', `t0`.`order_date`), "
        "SAFE.PARSE_DATE('%d-%b-%Y', `t0`.`order_date`)) AS `order_date`,\n  "
        "`t0`.`Order Total` * 0.1 AS `tax`,\n  PARSE_DATE('%m/%d/%Y', `t0`.`order_date`) AS `parsed`\n"
        "FROM `project.data.raw` AS `t0`")


def test_union_context_derivations_bind_raw_columns_or_typed_nulls():
    sources = [{'id': 's_base', 'bq_table': 'project.data.raw', 'columns': [
        {'name': 'Order Total', 'bq_type': 'FLOAT'}]},
        {'id': 's_other', 'bq_table': 'project.data.other', 'columns': [{'name': 'group', 'bq_type': 'STRING'}]}]
    fields = [ArtifactField(name='tax', expression="IF(t0.`Order Total` > 0, t0.`Order Total`, 0)", type='number', description='')]
    sql = blueprint_sql(sources, ViewSources(base='s_base', joins=[], union=['s_other']), fields, context_fields=['tax'])
    assert 'IF(`t0`.`Order Total` > 0, `t0`.`Order Total`, 0) AS `tax`' in sql
    assert 'IF(CAST(NULL AS FLOAT64) > 0, CAST(NULL AS FLOAT64), 0) AS `tax`' in sql
    assert sql.count('UNION ALL') == 1


def test_context_derivation_literals_are_not_rewritten_and_join_is_unambiguous():
    selection = ViewSources(base='s_sales', joins=[{'source_id': 's_groups', 'on': [
        {'left': 'order', 'right': 'order'}]}], union=[])
    field = ArtifactField(name='label', expression="IF(`order` > 0, '`order`', 't0.order')", type='string', description='')
    sql = blueprint_sql(UNION_SOURCES, selection, [field], context_fields=['label'])
    assert "IF(`t0`.`order` > 0, '`order`', 't0.order') AS `label`" in sql


def test_nested_column_projection_is_string_and_scalar_fields_still_work():
    source = {'id': 's_base', 'bq_table': 'project.data.raw', 'columns': [
        {'name': 'payload', 'bq_type': 'RECORD', 'type': 'string'},
        {'name': 'revenue', 'bq_type': 'FLOAT', 'type': 'number'}]}
    selection = ViewSources(base='s_base', joins=[], union=[])
    assert blueprint_fields([source], selection, [])[0] == {'name': 'payload', 'type': 'STRING', 'role': 'dimension'}
    assert 'TO_JSON_STRING(`t0`.`payload`) AS `payload`' in blueprint_sql([source], selection, [])


def test_context_struct_member_matching_top_level_column_keeps_its_path():
    source = {'id': 's_base', 'bq_table': 'project.data.raw', 'columns': [
        {'name': 'payload', 'bq_type': 'RECORD', 'type': 'string'},
        {'name': 'city', 'bq_type': 'STRING', 'type': 'string'}]}
    field = ArtifactField(name='home_city', expression='t0.payload.city', type='string', description='')
    sql = blueprint_sql([source], ViewSources(base='s_base', joins=[], union=[]), [field], context_fields=['home_city'])
    assert '`t0`.`payload`.`city` AS `home_city`' in sql
    assert '`payload`.`t0`' not in sql


def test_actual_profile_preserves_repeated_mode_for_view_projection():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from google.cloud import bigquery
    from dss.data.profile import profile_table
    schema = [bigquery.SchemaField('items', 'INTEGER', mode='REPEATED'),
              bigquery.SchemaField('tags', 'STRING', mode='REPEATED')]
    stats = {'null_count': 0, 'distinct_count': 1, 'value_counts': [{'value': '[1]', 'count': 2}],
             'min_value': None, 'max_value': None, 'invalid_dates': 0}
    client = Mock()
    client.get_table.return_value.schema = schema
    client.query.return_value.result.return_value = [{'row_count': 2, 'c0': stats, 'c1': stats}]
    service = SimpleNamespace(client=client, config=SimpleNamespace(bq_location='US'))
    profile = profile_table(service, 'project.data.arrays')
    source = {'id': 's_base', 'bq_table': 'project.data.arrays', **profile}
    assert all(c['mode'] == 'REPEATED' for c in profile['columns'])
    selection = ViewSources(base='s_base', joins=[], union=[])
    assert all(f['type'] == 'STRING' and f['role'] == 'dimension' for f in blueprint_fields([source], selection, []))
    sql = blueprint_sql([source], selection, [])
    assert 'TO_JSON_STRING(`t0`.`items`) AS `items`' in sql
    assert 'TO_JSON_STRING(`t0`.`tags`) AS `tags`' in sql
