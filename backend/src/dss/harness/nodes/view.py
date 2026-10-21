"""Deterministic per-version view SELECT from validated planning metadata."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from dss.data.bigquery import quoted, table_uri, snake_names


class DerivedField(BaseModel):
    """Validated SQL builder input (independent of any model node)."""
    model_config = ConfigDict(extra='forbid')
    name: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    sql: str = Field(min_length=1, max_length=2000)
    type: Literal['STRING', 'INTEGER', 'FLOAT', 'NUMERIC', 'DATE', 'TIMESTAMP', 'BOOLEAN']


class Join(BaseModel):
    model_config = ConfigDict(extra='forbid')
    table: str
    on: str = Field(min_length=1, max_length=2000)


def field_name(value):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise ValueError("Field names must be snake_case")
    return value


def expression(value, identifiers=()):
    # Expressions may contain SQL functions, but may never introduce a statement,
    # comment or subquery. Source access is restricted to the profiled tables.
    # Hide quoted tokens before checking statement words: 'UPDATE' is valid data,
    # and `select` is a valid column identifier.
    token = re.compile(r"(?i:\b(?:r|b|rb|br))?(?:'(?:\\.|''|[^'\\])*'|\"(?:\\.|\"\"|[^\"\\])*\")|`(?:\\.|[^`\\])*`")
    bare = token.sub(lambda match: " " * len(match.group()), value)
    if (not value.strip() or any(char in bare for char in "'\"`") or
            re.search(r";|--|/\*|\*/|\b(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|EXPORT|EXECUTE)\b", bare, re.I)):
        raise ValueError("Expected one SQL expression without statements or subqueries")
    # Rewrite only known source identifiers and qualified references. SQL type
    # names, date parts and other syntax stay with BigQuery's own parser.
    word = re.compile(token.pattern + r"|\b[A-Za-z_][A-Za-z0-9_]*\b")
    def quote_word(match):
        text = match.group()
        before, after = value[:match.start()].rstrip(), value[match.end():].lstrip()
        if token.fullmatch(text) or after.startswith("("):
            return text
        if before.endswith(".") or re.fullmatch(r"t[0-9]+", text):
            return quoted(text)
        if text in identifiers and not re.search(r"\bAS$", before, re.I) and not after.startswith(("'", '"')):
            return quoted(text)
        return text
    return word.sub(quote_word, value)


def select_sql(sources, fields, joins):
    if not sources:
        raise ValueError("A view requires a base source")
    by_table = {s["bq_table"]: s for s in sources}
    selected = [sources[0]]
    for join in joins:
        if join.table not in by_table or join.table in [s["bq_table"] for s in selected]:
            raise ValueError("Join table must be a distinct connected source")
        selected.append(by_table[join.table])
    identifiers = {col["name"] for source in selected for col in source["columns"]}
    columns, used = [], set()
    for index, source in enumerate(selected):
        names = snake_names([col["name"] for col in source["columns"]])
        for col, name in zip(source["columns"], names):
            # Common join keys occur in both tables. Expose the first one only.
            if name in used:
                continue
            used.add(name)
            ref = f'{quoted("t" + str(index))}.{quoted(col["name"])}'
            if col.get("date_like") and col.get("bq_type", "STRING") == "STRING":
                formats = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y")
                ref = "COALESCE(" + ", ".join(f"SAFE.PARSE_DATE('{fmt}', {ref})" for fmt in formats) + ")"
            columns.append(f"{ref} AS {quoted(name)}")
    for field in fields:
        name = field_name(field.name)
        if name in used:
            raise ValueError("Field names must be unique")
        used.add(name)
        columns.append(f"{expression(field.sql, identifiers)} AS {quoted(name)}")
    if not columns:
        raise ValueError("A view requires columns")
    sql = "SELECT\n  " + ",\n  ".join(columns) + f'\nFROM {quoted(table_uri(selected[0]["bq_table"]))} AS `t0`'
    for index, join in enumerate(joins, 1):
        sql += f'\nLEFT JOIN {quoted(table_uri(join.table))} AS {quoted("t" + str(index))} ON {expression(join.on, identifiers)}'
    return sql


def view_table(config, build_id, version, run_id):
    return table_uri(f"{config.gcp_project_id}.{config.bq_dataset}.dash_{build_id}_v{version}_{run_id}")


API_TYPES = {'string': 'STRING', 'number': 'FLOAT64', 'date': 'DATE',
             'datetime': 'TIMESTAMP', 'boolean': 'BOOL', 'geo': 'GEOGRAPHY'}
ALIASES = {'INTEGER': 'INT64', 'FLOAT': 'FLOAT64', 'BOOLEAN': 'BOOL', 'DECIMAL': 'NUMERIC',
           'BIGDECIMAL': 'BIGNUMERIC'}
SQL_TYPES = {'STRING', 'INT64', 'FLOAT64', 'NUMERIC', 'BIGNUMERIC', 'DATE', 'TIMESTAMP',
             'DATETIME', 'TIME', 'BOOL', 'GEOGRAPHY', 'BYTES', 'JSON'}


def column_type(column):
    if column.get('mode') == 'REPEATED' or column.get('bq_type') in ('RECORD', 'STRUCT'):
        return 'STRING'
    kind = column.get('bq_type') or API_TYPES.get(column.get('type'), 'STRING')
    kind = ALIASES.get(kind.upper(), kind.upper())
    if column.get('date_like') and kind == 'STRING':
        kind = 'DATE'
    if kind not in SQL_TYPES:
        raise ValueError('Unsupported view column type')
    return kind


def selected_sources(sources, selection):
    """Resolve only structured source IDs, never a model-provided table name or join SQL."""
    by_id = {s['id']: s for s in sources}
    ids = [selection.base, *[j.source_id for j in selection.joins], *selection.union]
    if selection.joins and selection.union:
        raise ValueError('Choose joins or union, never both')
    if len(set(ids)) != len(ids) or any(sid not in by_id for sid in ids):
        raise ValueError('View sources must be distinct connected source IDs')
    return [by_id[sid] for sid in ids]


def _columns(source):
    return list(zip(snake_names([c['name'] for c in source['columns']]), source['columns']))


def _ref(column, alias):
    ref = f'{quoted(alias)}.{quoted(column["name"])}'
    if column.get('mode') == 'REPEATED' or column.get('bq_type') in ('RECORD', 'STRUCT'):
        return f'TO_JSON_STRING({ref})'
    if column.get('date_like') and (column.get('bq_type') or 'STRING') == 'STRING':
        formats = ('%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d', '%d-%b-%Y')
        ref = 'COALESCE(' + ', '.join(f"SAFE.PARSE_DATE('{fmt}', {ref})" for fmt in formats) + ')'
    return ref


def _projection(sources, selection):
    selected = selected_sources(sources, selection)
    fields = {}
    for source in selected:
        for name, column in _columns(source):
            kind = column_type(column)
            if name in fields and selection.union and fields[name] != kind:
                numeric = {'INT64', 'NUMERIC', 'BIGNUMERIC', 'FLOAT64'}
                if {fields[name], kind} <= numeric:
                    fields[name] = max((fields[name], kind), key=lambda t: ['INT64', 'NUMERIC', 'BIGNUMERIC', 'FLOAT64'].index(t))
                else:
                    raise ValueError('Union columns with the same name need compatible types')
            fields.setdefault(name, kind)
    if selection.union:
        if 'dataset_name' in fields:
            raise ValueError('dataset_name is reserved for union provenance')
        fields['dataset_name'] = 'STRING'
    return selected, fields


def blueprint_fields(sources, selection, derived):
    """The view's actual projected names/types and spec roles, shared by prompt and validation."""
    _, fields = _projection(sources, selection)
    for field in derived:
        if field.name in fields:
            raise ValueError('Field names must be unique')
        fields[field.name] = API_TYPES[field.type]
    return [{'name': name, 'type': kind, 'role': 'metric' if kind in
             {'INT64', 'FLOAT64', 'NUMERIC', 'BIGNUMERIC'} else 'dimension'} for name, kind in fields.items()]


def _scalar(value, identifiers):
    from dss.harness.nodes.context import AGGREGATE, QUOTED
    safe = expression(value, identifiers)
    if AGGREGATE.search(QUOTED.sub(' ', safe)):
        raise ValueError('Derived fields must be scalar expressions without aggregates or windows')
    return safe


def _context_expression(field, base, source, index):
    """Context validated raw base columns under t0, before aliases/date conversions.

    For a union branch, bind the same normalized fields to that branch's raw
    columns, using typed NULL for missing fields. Never rewrite inside literals.
    """
    raw = {col['name']: (name, col) for name, col in _columns(base)}
    safe = _scalar(field.expression, raw)
    available = dict(_columns(source))
    identifier = r'`(?:\\.|[^`\\])*`'
    literal = r"(?i:\b(?:r|b|rb|br))?(?:'(?:\\.|''|[^'\\])*'|\"(?:\\.|\"\"|[^\"\\])*\")"
    token = re.compile(literal + '|' + identifier + r'(?:\s*\.\s*' + identifier + ')*')
    missing_nested = False
    def bind(match):
        nonlocal missing_nested
        text = match.group()
        if not text.startswith('`'):
            return text
        if safe[:match.start()].rstrip().endswith('.'):
            return text  # a member following an array subscript is not a source field
        parts = re.findall(identifier, text)
        names = [p[1:-1].replace('\\`', '`').replace('\\\\', '\\') for p in parts]
        root = 1 if len(names) > 1 and names[0] == 't0' else 0
        name = names[root]
        if name not in raw:
            return text
        normalized, original = raw[name]
        target = available.get(normalized)
        original_kind = original.get('bq_type') or API_TYPES.get(original.get('type'), 'STRING')
        original_kind = ALIASES.get(original_kind, original_kind)
        if original_kind not in SQL_TYPES or original.get('mode') == 'REPEATED':
            if target is None:
                missing_nested = True
                return 'NULL'
        if target is None:
            ref = f'CAST(NULL AS {original_kind})'
        else:
            ref = f'{quoted(f"t{index}")}.{quoted(target["name"])}'
            target_kind = target.get('bq_type') or API_TYPES.get(target.get('type'), 'STRING')
            target_kind = ALIASES.get(target_kind, target_kind)
            if target_kind != original_kind and original_kind in SQL_TYPES:
                ref = f'SAFE_CAST({ref} AS {original_kind})'
        if len(parts) > root + 1:
            ref += '.' + '.'.join(parts[root + 1:])  # preserve the complete STRUCT path
        return ref
    result = token.sub(bind, safe)
    return f'CAST(NULL AS {API_TYPES[field.type]})' if missing_nested else result


def blueprint_sql(sources, selection, derived, *, context_fields=()):
    """Code-built join/union SELECT, then scalar derivations over the normalized projection.

    No DDL, chart filters, arbitrary join clauses or model-supplied source URIs.
    """
    selected, fields = _projection(sources, selection)
    blueprint_fields(sources, selection, derived)  # collision check before SQL construction
    confirmed = [f for f in derived if f.name in context_fields]
    extra = [f for f in derived if f.name not in context_fields]
    if selection.union:
        branches = []
        for index, source in enumerate(selected):
            columns = dict(_columns(source))
            output = []
            for name, kind in fields.items():
                if name == 'dataset_name':
                    # Source IDs are bound as literals with the same escaping as identifiers.
                    literal = source['id'].replace('\\', '\\\\').replace("'", "\\'")
                    ref = f"'{literal}'"
                elif name not in columns:
                    ref = f'CAST(NULL AS {kind})'
                else:
                    ref = _ref(columns[name], f't{index}')
                    if column_type(columns[name]) != kind:
                        ref = f'CAST({ref} AS {kind})'
                output.append(f'{ref} AS {quoted(name)}')
            for field in confirmed:
                output.append(f'{_context_expression(field, selected[0], source, index)} AS {quoted(field.name)}')
            branches.append('SELECT\n  ' + ',\n  '.join(output) +
                            f'\nFROM {quoted(table_uri(source["bq_table"]))} AS {quoted(f"t{index}")}')
        sql = '\nUNION ALL\n'.join(branches)
    else:
        output, exposed = [], {}
        clauses = ''
        for index, source in enumerate(selected):
            columns = dict(_columns(source))
            if index:
                join = selection.joins[index - 1]
                if not join.on:
                    raise ValueError('A join requires at least one key')
                conditions = []
                for key in join.on:
                    if key.left not in exposed or key.right not in columns:
                        raise ValueError('Join keys must exist in the preceding sources and joined source')
                    left_index, left = exposed[key.left]
                    right = columns[key.right]
                    if column_type(left) != column_type(right):
                        raise ValueError('Join keys must have equal types')
                    conditions.append(f'{_ref(left, f"t{left_index}")} = {_ref(right, f"t{index}")}')
                clauses += f'\nLEFT JOIN {quoted(table_uri(source["bq_table"]))} AS {quoted(f"t{index}")} ON ' + ' AND '.join(conditions)
            for name, col in columns.items():
                if name not in exposed:
                    exposed[name] = (index, col)
                    output.append(f'{_ref(col, f"t{index}")} AS {quoted(name)}')
        for field in confirmed:
            output.append(f'{_context_expression(field, selected[0], selected[0], 0)} AS {quoted(field.name)}')
        if not output:
            raise ValueError('A view requires columns')
        sql = 'SELECT\n  ' + ',\n  '.join(output) + f'\nFROM {quoted(table_uri(selected[0]["bq_table"]))} AS `t0`' + clauses
    if extra:
        fields = {**fields, **{f.name: API_TYPES[f.type] for f in confirmed}}
        output = [quoted(name) for name in fields]
        for field in extra:
            safe = _scalar(field.expression, fields)
            output.append(f'{safe} AS {quoted(field.name)}')
        sql = 'SELECT\n  ' + ',\n  '.join(output) + '\nFROM (\n' + sql + '\n) AS `base`'
    return sql
