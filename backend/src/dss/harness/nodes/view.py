"""Deterministic per-version view SELECT from validated planning metadata."""
import re
from dss.data.bigquery import quoted, table_uri, snake_names


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


def view_table(config, build_id, version):
    return table_uri(f"{config.gcp_project_id}.{config.bq_dataset}.dash_{build_id}_v{version}")
