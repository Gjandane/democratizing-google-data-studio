"""31.1 oracle: component titles never carry ` | agg(field) [unit]`, and one grain word on a trend
sets its grain when its date field has none (architecture.md#Component titles and grain words)."""
from copy import deepcopy
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re

import pytest
from jsonschema import Draft202012Validator

from dss.artifacts.models import Blueprint, DerivedField, Design, Outline
from dss.harness.nodes import blueprint as node
from dss.harness.nodes.revise import Change, Operation, Revision, revised
from dss.recipe.compiler import compile_recipe
from dss.render.prototype import aggregate_sql, render
from dss.spec.auto_layout import spec_value
from dss.spec.models import DashboardSpec, clean_title, grain_word
from test_blueprint import blueprint_api, confirm, fixture  # noqa: F401  (fixture)
from test_context_node import context_api  # noqa: F401  (fixture)
from test_render import blueprint_flow  # noqa: F401  (fixture)

SCHEMA = json.loads(Path('../contracts/recipe.schema.json').read_text(encoding='utf-8'))
# The manual oracle's pattern, plus any aggregation call or bracketed unit anywhere.
SUFFIX = re.compile(r'\| *(sum|avg|count|count_distinct|min|max)\(|\[[^\]]+\]$')
FORMULA = re.compile(r'\b(sum|avg|count|count_distinct|min|max|none)\(|\[[^\]]*\]|\s\|\s', re.I)

# Hosted build b_302d91fd3a0f's 14 component labels (v1 recipe titles, its two pre-comment
# scorecards as drafted) -> the clean titles.
B302 = {
    'Total Revenue (USD) | sum(revenue) [USD]': 'Total Revenue (USD)',
    'Total Orders | count_distinct(order_id) [orders]': 'Total Orders',
    'Units Sold': 'Units Sold',
    'Average Unit Price (USD) | avg(unit_price) [USD]': 'Average Unit Price (USD)',
    'Monthly Total Revenue Trend (Jan - Sep 2026) | sum(revenue) [USD]': 'Monthly Total Revenue Trend (Jan - Sep 2026)',
    'Monthly Order Volume vs. Units Sold | count_distinct(order_id), sum(quantity) [count]':
        'Monthly Order Volume vs. Units Sold',
    'Revenue and Order Volume by Region | sum(revenue) [USD], count_distinct(order_id) [orders]':
        'Revenue and Order Volume by Region',
    'Regional Share of Total Revenue | sum(revenue) [USD]': 'Regional Share of Total Revenue',
    'Total Revenue by Country and Region | sum(revenue) [USD]': 'Total Revenue by Country and Region',
    'Total Revenue and Units Sold by Product Category | sum(revenue) [USD], sum(quantity) [units]':
        'Total Revenue and Units Sold by Product Category',
    'Product Average Unit Price vs. Total Revenue | avg(unit_price) [USD] vs sum(revenue) [USD]':
        'Product Average Unit Price vs. Total Revenue',
    'Product Performance Detail | sum(revenue) [USD], avg(unit_price) [USD]': 'Product Performance Detail',
    'High-Value Order Revenue (>= $1,000) by Region and Segment | sum(high_value_revenue) [USD], '
    'count_distinct(high_value_order_id) [orders]': 'High-Value Order Revenue (>= $1,000) by Region and Segment',
    'Regional and Segment Order Summary (Overall vs. High-Value >= $1,000) | sum(revenue) [USD], '
    'count_distinct(order_id) [orders]': 'Regional and Segment Order Summary (Overall vs. High-Value >= $1,000)',
}
LABELS = list(B302)


def test_title_rule_on_the_b302_labels_and_its_edges():
    assert {label: clean_title(label) for label in LABELS} == B302
    for kept in ('Units Sold', 'Avg Unit Price', 'Revenue | Q3', 'Total Revenue (USD)', 'Order Count (distinct)', ''):
        assert clean_title(kept) is kept  # byte for byte
    # A formula-only label becomes the metric's name; two metrics are joined by " and ".
    assert clean_title('sum(revenue)', ['revenue']) == 'Revenue'
    assert clean_title('SUM(revenue) [USD]') == 'Revenue'
    assert clean_title('count_distinct(order_id), sum(quantity) [count]', ['order_id', 'quantity']) == 'Order Id and Quantity'
    assert clean_title('[USD]', ['unit_price']) == 'Unit Price'
    assert clean_title('Revenue | Q3 | sum(revenue)') == 'Revenue | Q3'
    assert clean_title('Revenue [USD]') == 'Revenue'
    assert clean_title('Revenue | [USD]') == 'Revenue'


@pytest.mark.parametrize('texts, grain', [
    (('Monthly Revenue',), 'month'), (('Revenue by month',), 'month'), (('Revenue', 'Trend month over month?'), 'month'),
    (('Daily orders',), 'day'), (('Orders per day',), 'day'), (('Weekly revenue',), 'week'),
    (('Quarterly revenue',), 'quarter'), (('Annual revenue',), 'year'), (('Revenue year over year',), 'year'),
    (('Weekly and monthly revenue',), None), (('Monthly revenue', 'week by week?'), None),
    (('Revenue trend',), None), (('Monthlyish revenue',), None), (('Revenue annually',), None)])
def test_grain_words(texts, grain):
    assert grain_word(*texts) == grain


def b302_rows(value):
    """The FakeLLM blueprint carrying the 14 b_302d91fd3a0f labels on this oracle's fields."""
    rows = value['rows']
    by = lambda qid, n=0: [r for r in rows if r['question_id'] == qid][n]
    def extra(base, label, **component):
        row = deepcopy(base)
        row['component'].update(label=label, **component)
        rows.append(row)
    q1, q3, q4, q5, q7 = by('q1'), by('q3'), by('q4'), by('q5'), by('q7')
    q1['component']['label'] = LABELS[0]
    by('q1', 1)['component']['label'] = LABELS[1]
    by('q1', 2)['component']['label'] = LABELS[2]
    by('q2')['component']['label'] = LABELS[3]
    q3['component']['label'] = LABELS[4]
    extra(q3, LABELS[5], metrics=[{'field': 'order_id', 'agg': 'count_distinct'}, {'field': 'quantity', 'agg': 'sum'}])
    extra(q4, LABELS[6], metrics=[{'field': 'revenue', 'agg': 'sum'}, {'field': 'order_id', 'agg': 'count_distinct'}])
    extra(q4, LABELS[7], type='pie', sort=None)
    q4['component']['label'] = LABELS[8]
    extra(q5, LABELS[10], type='scatter', sort=None, options={},
          metrics=[{'field': 'quantity', 'agg': 'avg'}, {'field': 'revenue', 'agg': 'sum'}])
    extra(q5, LABELS[11], type='table', sort=None, options={},
          metrics=[{'field': 'revenue', 'agg': 'sum'}, {'field': 'quantity', 'agg': 'avg'}])
    q5['component'].update(label=LABELS[9], metrics=[{'field': 'revenue', 'agg': 'sum'}, {'field': 'quantity', 'agg': 'sum'}])
    q7['component']['label'] = LABELS[12]
    extra(q7, LABELS[13], type='table', dimensions=['region'], options={},
          metrics=[{'field': 'revenue', 'agg': 'sum'}, {'field': 'order_id', 'agg': 'count_distinct'}])
    return value


@pytest.fixture
def b302(blueprint_api):
    *_, llm, value = blueprint_api
    llm.replies = [json.dumps(b302_rows(value))]


def clean(label):
    return not FORMULA.search(label) and not SUFFIX.search(label)


def test_b302_labels_draft_as_clean_blueprint_rows(b302, blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    confirm(client, app, bid)
    draft = client.get(f'/api/builds/{bid}/blueprint').json()
    assert llm.calls == 1
    labels = [r['component']['label'] for r in draft['rows'] if r['question_id']]
    assert sorted(labels) == sorted(B302.values())
    markdown = (folder / 'docs/blueprint.md').read_text(encoding='utf-8')
    # Its Fields column shows sum(revenue) as before; no title keeps a suffix.
    assert not [label for label, title in B302.items() if label != title and label.split(' | ')[1] in markdown]
    assert all(clean(label) for label in labels)


def test_b302_spec_prototype_ids_and_recipe_carry_clean_titles(b302, blueprint_flow):
    client, app, bid, folder, bq, run_id = blueprint_flow
    spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8'))
    components = [c for p in spec.pages for c in p.components]
    labels = {c.label for c in components}
    # q2's ratio row became the code-built numerator/denominator scorecards (KPI names).
    assert set(B302.values()) - {'Average Unit Price (USD)'} <= labels
    assert all(clean(c.label) and not re.search(r'[(\[]', c.id) for c in components)
    assert {c.id for c in components} >= {'p1_total_revenue_usd', 'p1_total_orders', 'p1_units_sold',
                                          'p1_monthly_order_volume_vs_units_sold'}
    html = (folder / 'prototype.html').read_text(encoding='utf-8')
    shown = re.findall(r'data-kind="component"[^>]*', html)
    assert len(shown) == len(components)
    assert not FORMULA.search(' '.join(re.findall(r'data-label="([^"]*)"', html)))
    assert all(f'data-label="{escape(c.label, quote=True)}"' in html for c in components)
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200
    ops = [json.loads(line) for line in (folder / 'recipe.jsonl').read_text(encoding='utf-8').splitlines()]
    Draft202012Validator({**SCHEMA, '$ref': '#/$defs/header'}).validate(ops[0])
    for op in ops[1:]:
        Draft202012Validator({**SCHEMA, '$ref': '#/$defs/op'}).validate(op)
    charts = [op for op in ops[1:] if op['op'] == 'add_chart']
    assert {op['component_id']: op['title'] for op in charts} == {c.id: c.label for c in components if c.id in
                                                                  {op['component_id'] for op in charts}}
    assert len(charts) == len([c for c in components if c.type not in ('date_range', 'dropdown', 'fixed_size_list')])
    assert all(not SUFFIX.search(op['title']) and clean(op['title']) for op in charts)
    # Both "Monthly" trends on the daily order_date draw one point per month, in the report and the prototype.
    trends = [op for op in charts if op['chart_type'] == 'time_series']
    assert [(op['title'], op['date_dimension'], op['options']) for op in trends] == [
        ('Monthly Total Revenue Trend (Jan - Sep 2026)', 'order_date', {'date_granularity': 'month'}),
        ('Monthly Order Volume vs. Units Sold', 'order_date', {'date_granularity': 'month'})]
    assert all('date_granularity' not in op['options'] for op in charts if op['chart_type'] != 'time_series')
    assert not [f for f in spec.datasource.fields if f.date_granularity]  # order_date stays a raw date
    cache = json.loads((folder / 'aggregate-cache.json').read_text(encoding='utf-8'))
    for c in components:
        if c.type == 'time_series':
            assert c.date_granularity == 'month'
            sql = aggregate_sql(spec, c)
            assert sql.startswith('SELECT DATE_TRUNC(`order_date`, MONTH) AS `order_date`, ')
            assert ' GROUP BY DATE_TRUNC(`order_date`, MONTH) ORDER BY `order_date` ASC' in sql
            assert sha256(sql.encode()).hexdigest() in cache  # the query the prototype ran
        else:
            assert c.date_granularity is None and 'TRUNC' not in (aggregate_sql(spec, c) or '')


def test_a_revised_title_passes_the_rule_and_a_patch_never_sets_a_grain(b302, blueprint_flow):
    client, app, bid, folder, bq, run_id = blueprint_flow
    document = json.loads((folder / 'spec.json').read_text(encoding='utf-8'))
    components = document['pages'][0]['components']
    units = next(i for i, c in enumerate(components) if c['label'] == 'Units Sold')
    trend = next(i for i, c in enumerate(components) if c['type'] == 'time_series')
    allowed = {c['type'] for p in document['pages'] for c in p['components']}

    def revise(index, *ops):
        patch = [Operation(op=op, path=f'/pages/0/components/{index}/{key}', value=v) for op, key, v in ops]
        batch = Revision(changes=[Change(comment_index=0, patch=patch)])
        candidate, _ = revised(document, [{'component_id': components[index]['id'], 'text': 'x'}], batch, allowed)
        return candidate['pages'][0]['components'][index]

    assert revise(units, ('replace', 'label', 'Avg Unit Price'))['label'] == 'Avg Unit Price'
    assert revise(units, ('replace', 'label', 'Avg Unit Price | avg(unit_price) [USD]'))['label'] == 'Avg Unit Price'
    assert revise(units, ('replace', 'label', 'avg(unit_price) [USD]'))['label'] == 'Quantity'
    assert revise(units, ('add', 'date_granularity', 'day')).get('date_granularity') is None
    # A patch's grain is never kept: code redraws it from the revised title's words.
    assert revise(trend, ('replace', 'date_granularity', 'day'))['date_granularity'] == 'month'
    revised_trend = revise(trend, ('replace', 'date_granularity', 'day'),
                           ('replace', 'label', 'Weekly Revenue | sum(revenue) [USD]'))
    assert (revised_trend['label'], revised_trend['date_granularity']) == ('Weekly Revenue', 'week')
    # A title naming no grain keeps the grain its question gave; leaving the date axis drops it.
    assert revise(trend, ('replace', 'label', 'Revenue trend'))['date_granularity'] == 'month'
    assert revise(trend, ('replace', 'type', 'bar'), ('add', 'dimensions', ['order_date'])).get('date_granularity') is None
    assert revise(units, ('replace', 'label', 'Daily Units')).get('date_granularity') is None  # not a trend


def test_row_repair_and_redraft_rows_pass_the_title_rule(blueprint_api):
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    missing = deepcopy([r for r in value['rows'] if r['question_id'] == 'q4'])
    missing[0]['component']['label'] = 'Total Revenue by Region | sum(revenue) [USD]'
    first = {**value, 'rows': [r for r in value['rows'] if r['question_id'] != 'q4']}
    llm.replies = [json.dumps(first), json.dumps({'rows': missing})]
    confirm(client, app, bid)
    assert llm.calls == 2
    labels = {r.question_id: r.component.label for r in node.load(folder).rows}
    assert labels['q4'] == 'Total Revenue by Region'
    # Redraft: an edited question is drafted again and its new row is cleaned too.
    outline = Outline.model_validate(fixture('outline'))
    outline.sections[1].questions[0].text = 'Which regions have the lowest net revenue?'
    from test_blueprint import artifact
    artifact(folder, outline)
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=? WHERE id=?', ('design', bid))
    again = deepcopy(missing[0])
    again['component']['label'] = 'sum(revenue) [USD]'
    llm.replies.append(json.dumps({**value, 'rows': [again]}))
    confirm(client, app, bid)
    rows = node.load(folder).rows
    assert llm.calls == 3 and next(r for r in rows if r.question_id == 'q4').component.label == 'Revenue'
    assert all(clean(r.component.label) for r in rows)


FIELDS = [{'name': n, 'type': t, 'role': r} for n, t, r in [
    ('order_date', 'DATE', 'dimension'), ('order_week', 'DATE', 'dimension'), ('order_time', 'TIMESTAMP', 'dimension'),
    ('weekday', 'STRING', 'dimension'), ('region', 'STRING', 'dimension'), ('category', 'STRING', 'dimension'),
    ('customer_segment', 'STRING', 'dimension'), ('order_size_band', 'STRING', 'dimension'),
    ('revenue', 'FLOAT', 'metric'), ('order_id', 'STRING', 'dimension')]]


def laid_out(label, date='order_date', question=None, sources=()):
    """Code layout of the fixture Blueprint with its q3 trend relabelled (and its question text)."""
    value = fixture('blueprint')
    value['derived_fields'].append({'name': 'order_week', 'expression': 'DATE_TRUNC(order_date, WEEK)',
                                    'type': 'date', 'description': 'Week'})
    trend = next(r for r in value['rows'] if r['question_id'] == 'q3')
    trend['component'].update(label=label, date_dimension=date)
    outline = fixture('outline')
    if question is not None:
        next(q for s in outline['sections'] for q in s['questions'] if q['id'] == 'q3')['text'] = question
    spec = DashboardSpec.model_validate(spec_value(Blueprint.model_validate(value), Design.model_validate(fixture('design')),
        Outline.model_validate(outline), FIELDS, build_id='b_3f9a0c12d4e5', archetype='sales', sources=sources))
    component = next(c for p in spec.pages for c in p.components if c.type == 'time_series')
    recipe = [json.loads(line) for line in compile_recipe(spec, 1).splitlines()]
    op = next(o for o in recipe if o.get('component_id') == component.id)
    return spec, component, op['options'].get('date_granularity')


@pytest.mark.parametrize('label, date, question, recorded, compiled', [
    ('Monthly Revenue | sum(revenue) [USD]', 'order_date', 'How does revenue trend?', 'month', 'month'),
    ('Revenue trend', 'order_date', None, 'month', 'month'),  # the question says "month over month"
    ('Revenue trend', 'order_date', 'How does revenue trend?', None, None),
    ('Daily revenue', 'order_time', 'How does revenue trend?', 'day', 'day'),
    ('Monthly Revenue', 'order_week', None, None, 'week'),  # a DATE_TRUNC week field keeps week
    ('Weekly and monthly revenue', 'order_date', 'How does revenue trend?', None, None),
    ('Weekly revenue', 'order_date', None, None, None),  # label week, question month: two grains
    ('Revenue per day of week', 'weekday', 'How does revenue trend?', None, None),
    ('Revenue per day of week', 'order_date', 'How does revenue trend?', 'day', 'day')])
def test_layout_records_one_grain_word_and_bucket_fields_keep_theirs(label, date, question, recorded, compiled):
    spec, component, grain = laid_out(label, date, question)
    assert (component.date_granularity, grain) == (recorded, compiled)
    assert clean(component.label) and not re.search(r'[(\[]', component.id)
    sql = aggregate_sql(spec, component)
    truncated = f'TRUNC(`{date}`, {recorded.upper()}) AS `{date}`' if recorded else None
    assert (truncated in sql) if truncated else 'TRUNC' not in sql
    if recorded and date == 'order_time':
        assert 'TIMESTAMP_TRUNC(`order_time`, DAY)' in sql


def test_a_bucket_start_column_is_never_drawn_finer():
    sources = [{'id': 's_a1b2c3d4e5f6', 'columns': [{'name': 'order_date', 'bq_type': 'DATE', 'bucket_start': 'quarter'}]}]
    spec, component, grain = laid_out('Daily Revenue', sources=sources)
    assert (component.date_granularity, grain) == (None, 'quarter')
    assert 'TRUNC' not in aggregate_sql(spec, component)


def test_saved_specs_compile_clean_titles_and_unchanged_specs_byte_identically():
    golden = Path('tests/data/golden_spec.json').read_text(encoding='utf-8')
    spec = DashboardSpec.model_validate_json(golden)
    assert compile_recipe(spec, 3).encode('utf-8') == Path('tests/data/golden_recipe.jsonl').read_bytes()
    assert spec.model_dump_json(indent=2) == DashboardSpec.model_validate_json(golden).model_dump_json(indent=2)
    assert 'date_granularity' not in json.loads(golden)['pages'][0]['components'][0]
    # A spec saved before 31.1 still carrying a suffix compiles, and renders, with the clean title.
    trend = next(c for p in spec.pages for c in p.components if c.type == 'time_series')
    trend.label = 'Monthly Revenue Over Time | sum(revenue) [USD]'
    op = next(json.loads(line) for line in compile_recipe(spec, 3).splitlines() if trend.id in line and '"add_chart"' in line)
    assert op['title'] == 'Monthly Revenue Over Time' and 'date_granularity' not in op['options']  # no recorded grain
    html = render(spec)
    assert 'data-label="Monthly Revenue Over Time"' in html and '[USD]' not in html


def test_model_output_never_records_a_component_grain():
    """A Blueprint row's options.date_granularity is model output: the compiler drops it, and the spec's
    component grain comes from code layout only."""
    spec, component, grain = laid_out('Revenue trend', question='How does revenue trend?')
    assert (component.date_granularity, grain) == (None, None)
    value = fixture('blueprint')
    next(r for r in value['rows'] if r['question_id'] == 'q3')['component']['options'] = {'date_granularity': 'year'}
    spec = DashboardSpec.model_validate(spec_value(Blueprint.model_validate(value), Design.model_validate(fixture('design')),
        Outline.model_validate(fixture('outline')), FIELDS, build_id='b_3f9a0c12d4e5', archetype='sales'))
    trend = next(c for p in spec.pages for c in p.components if c.type == 'time_series')
    op = next(json.loads(line) for line in compile_recipe(spec, 1).splitlines() if trend.id in line and '"add_chart"' in line)
    assert (trend.date_granularity, op['options']) == ('month', {'date_granularity': 'month'})  # "month over month"


def test_derived_field_fixture_is_a_week_bucket():
    from dss.spec.auto_layout import bucket_grain
    assert bucket_grain(DerivedField(name='order_week', expression='DATE_TRUNC(order_date, WEEK)', type='date',
                                     description='Week').expression) == 'week'
