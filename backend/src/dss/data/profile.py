"""Aggregate-only source profiling and a deterministic, bounded prompt form.

Run: uv run python -m dss.data.profile project.dataset.table [--json]
"""
import argparse
import json
import sys

from dss.data.bigquery import invalid, quoted, table_uri

NUMBERS = {'INTEGER', 'INT64', 'FLOAT', 'FLOAT64', 'NUMERIC', 'BIGNUMERIC'}
DATES = {'DATE', 'TIMESTAMP', 'DATETIME', 'TIME'}
DATE_FORMATS = ('%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d', '%d-%b-%Y')


def expressions(field):
    name = quoted(field.name)
    kind = field.field_type
    nested = field.mode == 'REPEATED' or kind in ('RECORD', 'STRUCT')
    text = (f'TO_JSON_STRING({name})' if nested or kind == 'JSON' else
            f'ST_ASTEXT({name})' if kind == 'GEOGRAPHY' else
            f'TO_BASE64({name})' if kind == 'BYTES' else f'CAST({name} AS STRING)')
    # TO_JSON_STRING(NULL) is the literal "null"; keep SQL NULL for null/value stats.
    text = f'IF({name} IS NULL, NULL, {text})'
    api_type = ('string' if nested else 'number' if kind in NUMBERS else
                'date' if kind == 'DATE' else 'datetime' if kind in DATES else
                'boolean' if kind in ('BOOL', 'BOOLEAN') else 'geo' if kind == 'GEOGRAPHY' else 'string')
    date = ('COALESCE(' + ', '.join(f"SAFE.PARSE_DATE('{fmt}', {name})" for fmt in DATE_FORMATS) + ')'
            if kind == 'STRING' and not nested else None)
    ordered = name if not nested and kind in NUMBERS | DATES else date
    stats = [f'COUNTIF({name} IS NULL) AS null_count',
             f'APPROX_COUNT_DISTINCT({text}) AS distinct_count',
             # 20 full values + a possible null + three extra sample values.
             f'APPROX_TOP_COUNT({text}, 24) AS value_counts',
             f'MIN({ordered}) AS min_value' if ordered else 'NULL AS min_value',
             f'MAX({ordered}) AS max_value' if ordered else 'NULL AS max_value',
             f'COUNTIF({name} IS NOT NULL AND {date} IS NULL) AS invalid_dates' if date else '0 AS invalid_dates']
    return api_type, date is not None, 'STRUCT(' + ', '.join(stats) + ')'


def profile_table(service, table):
    """One metadata read and ONE aggregate query, independent of column count.

    Only aggregates cross the BigQuery boundary: samples are additional top-count
    values, not rows. Approximate counts are intentionally suitable for profiling.
    """
    table_uri(table)
    schema = service.client.get_table(table, timeout=10).schema
    if not schema:
        raise invalid('Source has no columns')
    fields = [expressions(field) for field in schema]
    sql = ('SELECT COUNT(*) AS row_count,\n' + ',\n'.join(
        f'  {stats} AS c{i}' for i, (_, _, stats) in enumerate(fields)) + f'\nFROM {quoted(table)}')
    row = next(iter(service.client.query(sql, location=service.config.bq_location,
                                          timeout=10).result(timeout=10)))
    count = row['row_count']
    if not count:
        raise invalid('Source has zero data rows')
    columns = []
    for i, (field, (api_type, string_date, _)) in enumerate(zip(schema, fields)):
        stats = row[f'c{i}']
        values = sorted(({'value': str(v['value']), 'count': int(v['count'])}
                         for v in stats['value_counts'] or [] if v['value'] is not None),
                        key=lambda v: (-v['count'], v['value']))
        # The top-count result also guards approximate distinct-count error at 20.
        complete = len(values) <= 20
        shown = values if complete else values[:5]
        samples = values[:3] if complete else values[5:8]
        date_like = bool(string_date and stats['null_count'] < count and stats['invalid_dates'] == 0)
        columns.append({'name': field.name, 'type': api_type, 'bq_type': field.field_type, 'mode': field.mode,
                        'null_pct': 100 * stats['null_count'] / count,
                        'distinct_count': stats['distinct_count'], 'date_like': date_like,
                        'min': str(stats['min_value']) if stats['min_value'] is not None and (not string_date or date_like) else None,
                        'max': str(stats['max_value']) if stats['max_value'] is not None and (not string_date or date_like) else None,
                        'values': [{'value': v['value'][:60], 'count': v['count']} for v in shown],
                        'values_complete': complete, 'sample': [v['value'][:60] for v in samples]})
    return {'row_count': count, 'columns': columns}


def prompt_text(profile):
    """Stable compact text shared by all nodes; never omit a column.

    Use a conservative 6,000 UTF-8 byte target for normal 30-column profiles
    (also below the offline 6k-token chars/4 budget). Drop samples, then reduce
    lists to five, then shorten displayed values. Schema names/types are kept
    verbatim even if an unusually long schema alone exceeds this target; the
    node's actual provider token budget remains authoritative.
    """
    def form(samples=True, limit=20, width=60):
        lines = [f'rows={profile["row_count"]}']
        for i, col in enumerate(profile['columns']):
            line = f'{col["name"]} {col["type"]}'
            if i >= 40:
                lines.append(line)
                continue
            if col.get('null_pct') == 100:
                lines.append(line + ' all null')
                continue
            line += f' null={col.get("null_pct", 0):.2f}% distinct~{col.get("distinct_count", 0)}'
            if col.get('min') is not None or col.get('max') is not None:
                line += ' range=' + json.dumps([col.get('min'), col.get('max')], ensure_ascii=False, separators=(',', ':'))
            values = sorted(col.get('values', []), key=lambda v: (-v['count'], str(v['value'])))[:limit]
            if values:
                line += (' values=' if col.get('values_complete') and len(values) == len(col['values']) else ' top=')
                line += json.dumps([[str(v['value'])[:width], v['count']] for v in values], ensure_ascii=False, separators=(',', ':'))
            if samples and col.get('sample'):
                line += ' samples=' + json.dumps(sorted(str(v)[:width] for v in col['sample']), ensure_ascii=False, separators=(',', ':'))
            lines.append(line)
        return '\n'.join(lines) + '\n'

    for args in ((True, 20, 60), (False, 20, 60), (False, 5, 60), (False, 5, 30), (False, 5, 15), (False, 5, 8)):
        text = form(*args)
        if len(text.encode('utf-8')) <= 6000:
            return text
    return text


def render_profiles(sources):
    return '# Data profile\n\n' + '\n'.join(
        f'## {source["name"]} (`{source["bq_table"]}`)\n\n```text\n{prompt_text(source)}```\n' for source in sources)


def main():
    from dss.config import Config
    from dss.data.bigquery import BigQuery
    from dss.harness.guardrails import RunError
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('table')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    config = Config.from_env()
    config.gcp_project_id = config.gcp_project_id.strip()
    try:
        profile = profile_table(BigQuery(config), args.table)
    except RunError as error:
        parser.exit(1, error.message + '\n')
    except Exception:
        # Provider exceptions can contain credentials or source content.
        parser.exit(1, 'Source could not be profiled; check BigQuery access and table name.\n')
    # Windows' default console codec cannot encode arbitrary source values.
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(profile, ensure_ascii=False, indent=2) if args.json else prompt_text(profile), end='\n' if args.json else '')


if __name__ == '__main__':
    main()
