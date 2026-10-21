"""Bounded public CSV/HTML table retrieval, also usable with python -m dss.data.research.

Only code handles rows. The research agent receives Table.metadata(), never the rows.
"""
import argparse
import csv
from dataclasses import dataclass, field
from html.parser import HTMLParser
import http.client
import io
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from dss.data.bigquery import snake_names

MAX_FETCHES = 20
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10000
MAX_TABLES = 40
MAX_SECONDS = 120


class RetrievalError(ValueError):
    """Messages are fixed strings; never expose provider errors or response bodies."""


def public_url(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or
                parsed.username or parsed.password or len(url) > 2048 or
                any(ord(c) < 33 or c in '<>"`\\' for c in url) or
                parsed.port not in (None, 80 if parsed.scheme == 'http' else 443)):
            raise ValueError
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', parsed.query, ''))
    except (ValueError, TypeError):
        raise RetrievalError('Invalid public HTTP URL') from None


def public_addresses(host, port):
    try:
        addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError
        return addresses
    except (OSError, ValueError):
        raise RetrievalError('Host must resolve only to public addresses') from None


def http_get(url, timeout):
    """One request, no redirects/retries/proxies. Pin validated DNS to prevent rebinding."""
    parsed = urlsplit(public_url(url))
    host, port = parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)
    address = public_addresses(host, port)[0]
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    started = time.monotonic()
    try:
        sock = socket.create_connection((address, port), timeout=timeout)
        connection.sock = sock
        if parsed.scheme == 'https':
            connection.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        transport_socket = connection.sock
        connection.request('GET', urlunsplit(('', '', parsed.path or '/', parsed.query, '')),
                           headers={'User-Agent': 'DSSResearch/1.0', 'Accept-Encoding': 'identity',
                                    'Accept': 'text/html,text/csv,application/csv'})
        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        if response.status in (301, 302, 303, 307, 308):
            return response.status, headers, b''
        if response.status != 200:
            return response.status, headers, b''
        if headers.get('content-encoding', 'identity').lower() != 'identity':
            raise RetrievalError('Compressed responses are unsupported')
        parts, size = [], 0
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise RetrievalError('Request timed out')
            transport_socket.settimeout(remaining)
            chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                break
            parts.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise RetrievalError('Response exceeds 2 MB')
        return response.status, headers, b''.join(parts)
    except RetrievalError:
        raise
    except Exception:
        raise RetrievalError('Public request failed') from None
    finally:
        connection.close()


def clean(value):
    return ' '.join(value.replace('\x00', '').split()).strip()


# A number with thousands separators, then footnote ([5]), estimate ((2025 est.), 2025e)) or
# symbol markers. Placeholder dashes in an otherwise numeric column load as empty (NULL).
MARK = r'\[[^\[\]]{1,12}\]|\((?:\d{4}\s?)?(?:est|e|f|p)\.?\)|\(\d{4}\)|\(?\d{4}[a-z]\)?|[*†‡]'
NUMBER = re.compile(rf'([-−]?(?:\d{{1,3}}(?:,\d{{3}})+|\d+)(?:\.\d+)?)(?:\s*(?:{MARK}))*')
PLACEHOLDERS = {'—', '–', '-', 'n/a', 'na', '…', '...'}
# Bare names only ("Total Recall" is a title); not average/mean, which also name real category rows.
TOTAL_NAME = re.compile(r'(?:(?:grand |sub-?)?totals?|world|all|overall|sum)(?:\s*\([^()]*\))?', re.I)


def plain_number(cell):
    match = NUMBER.fullmatch(cell)
    return match[1].replace(',', '').replace('−', '-') if match else None


def normalize_numbers(rows):
    """Rewrite columns whose filled cells are all marked numbers; return their indexes."""
    numeric = set()
    for col in range(len(rows[0])):
        cells = [row[col] for row in rows if row[col] and row[col].casefold() not in PLACEHOLDERS]
        if cells and all(plain_number(cell) for cell in cells):
            numeric.add(col)
            for row in rows:
                row[col] = plain_number(row[col]) or ''
    return numeric


def aggregate_signals(rows, headers, numeric, title):
    """Deterministic per-row aggregate evidence: {row index: [reasons]}; 'total name' is decisive."""
    rank = next((col for col in sorted(numeric) if col < 2 and
                 sorted(int(row[col]) for row in rows if row[col].isdigit()) ==
                 list(range(1, sum(bool(row[col]) for row in rows) + 1)) and
                 sum(bool(row[col]) for row in rows) >= 3), None)
    label = next((col for col in range(len(headers)) if col not in numeric), None)
    reference = {i for i, row in enumerate(rows) if rank is None or row[rank]}
    sums = {}
    for col in numeric - {rank}:
        if len(reference) >= 3 and all(rows[i][col] for i in reference):
            sums[col] = sum(float(rows[i][col]) for i in reference)
    subject = title.casefold()
    signals = {}
    for i, row in enumerate(rows):
        reasons = []
        name = re.sub(r'\[[^\[\]]{1,12}\]', '', row[label]).strip() if label is not None else ''
        if name and TOTAL_NAME.fullmatch(name):
            reasons.append('total name')
        if rank is not None and not row[rank]:
            reasons.append('unranked row in a ranked table')
        if len(name) >= 2 and re.search(rf'(?<!\w){re.escape(name.casefold())}(?!\w)', subject):
            reasons.append('label names the table subject')
        for col, total in sums.items():
            if row[col]:
                others = total - (float(row[col]) if i in reference else 0)
                if others and abs(float(row[col]) - others) <= 0.01 * abs(others):
                    reasons.append(f'equals the sum of the other rows in {headers[col]}')
                    break
        if reasons:
            signals[i] = reasons
    return signals, label, rank


@dataclass
class Table:
    url: str
    title: str
    headers: list[str]
    rows: list[list[str]]
    # [{'label', 'reason'}]: aggregate rows left out of the CSV, and kept rows that may be one.
    excluded: list[dict] = field(default_factory=list)
    possible: list[dict] = field(default_factory=list)

    def metadata(self, number):
        return {'table_id': number, 'url': self.url, 'title': self.title[:200],
                'headers': self.headers, 'row_count': len(self.rows)}

    def csv_bytes(self):
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(snake_names(self.headers))
        writer.writerows(self.rows)
        return output.getvalue().encode('utf-8')


def make_table(url, title, headers, rows):
    headers = [clean(v) for v in headers]
    if not 2 <= len(headers) <= 100 or not any(headers) or len(rows) > MAX_ROWS:
        return None
    result, seen = [], set()
    for row in rows:
        row = [clean(v) for v in row]
        if not any(row):
            continue
        if len(row) != len(headers):
            # Do not shift ragged data into different columns.
            return None
        if row == headers:
            continue
        key = tuple(row)
        if key not in seen:
            seen.add(key)
            result.append(row)
    if not result:
        return None
    numeric = normalize_numbers(result)
    signals, label, rank = aggregate_signals(result, headers, numeric, clean(title))
    kept, excluded, possible = [], [], []
    for i, row in enumerate(result):
        reasons = signals.get(i, [])
        entry = {'label': row[label] if label is not None else f'row {i + 1}', 'reason': '; '.join(reasons)}
        # A ranked row is data. An unranked row in a ranked table plus a second signal, or a bare
        # total name, identifies an aggregate; anything less is a guess, kept and marked.
        unranked = 'unranked row in a ranked table' in reasons
        if 'total name' in reasons and (unranked or rank is None) or unranked and len(reasons) >= 2:
            excluded.append(entry)
            continue
        if reasons:
            possible.append(entry)
        kept.append(row)
    if not kept:
        return None
    return Table(url, clean(title), headers, kept, excluded, possible)


class TableParser(HTMLParser):
    """Read static tables, including comment-wrapped tables and row/column spans."""
    def __init__(self, comments=True):
        super().__init__(convert_charrefs=True)
        self.comments = comments
        self.tables = []
        self.depth = 0
        self.rows = []
        self.row = None
        self.cell = None
        self.caption = ''
        self.in_caption = False
        self.in_title = False
        self.title = ''
        self.skip = 0
        self.overflow = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'title':
            self.in_title = True
        if tag == 'table':
            self.depth += 1
            if self.depth == 1:
                self.rows, self.row, self.cell, self.caption = [], None, None, ''
                self.overflow = False
        if self.depth != 1:
            return
        if tag == 'caption':
            self.in_caption = True
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th') and self.row is not None:
            attrs = dict(attrs)
            try:
                rs, cs = int(attrs.get('rowspan', 1)), int(attrs.get('colspan', 1))
            except ValueError:
                rs, cs = 1, 1
            self.cell = ['', max(1, min(rs, 100)), max(1, min(cs, 100)), tag == 'th']
        if tag == 'br' and self.cell is not None:
            self.cell[0] += ' '

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag == 'title':
            self.in_title = False
        if self.depth == 1:
            if tag in ('td', 'th') and self.cell is not None:
                self.row.append(self.cell)
                self.cell = None
            if tag == 'tr' and self.row is not None:
                if len(self.rows) <= MAX_ROWS + 10:
                    self.rows.append(self.row)
                else:
                    self.overflow = True
                self.row = None
            if tag == 'caption':
                self.in_caption = False
            if tag == 'table' and len(self.tables) < MAX_TABLES and not self.overflow:
                self.tables.append((self.caption, self.rows))
        if tag == 'table':
            self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title += data
        if self.depth == 1 and self.in_caption:
            self.caption += data
        if self.depth == 1 and self.cell is not None:
            self.cell[0] += data

    def handle_comment(self, data):
        if self.comments and '<table' in data.lower() and not self.depth:
            parser = TableParser(comments=False)
            parser.feed(data)
            self.tables.extend(parser.tables[:MAX_TABLES - len(self.tables)])


def expand(rows):
    grid, spans = [], {}
    flags = []
    for cells in rows:
        row, col = [], 0
        all_headers = bool(cells) and all(cell[3] for cell in cells)
        for text, rowspan, colspan, _ in cells:
            while col in spans:
                value, left = spans.pop(col)
                row.append(value)
                if left > 1:
                    spans[col] = (value, left - 1)
                col += 1
            for _ in range(colspan):
                row.append(clean(text))
                if rowspan > 1:
                    spans[col] = (clean(text), rowspan - 1)
                col += 1
            if col > 100:
                return [], []
        while col in spans:
            value, left = spans.pop(col)
            row.append(value)
            if left > 1:
                spans[col] = (value, left - 1)
            col += 1
        if row:
            grid.append(row)
            flags.append(all_headers)
    return grid, flags


def parse_tables(url, content_type, content):
    charset = re.search(r'charset=["\']?([\w-]+)', content_type, re.I)
    try:
        text = content.decode(charset.group(1) if charset else 'utf-8-sig')
    except (UnicodeError, LookupError):
        raise RetrievalError('Unsupported text encoding') from None
    is_csv = 'csv' in content_type.lower() or urlsplit(url).path.lower().endswith('.csv')
    if is_csv:
        try:
            reader = csv.reader(io.StringIO(text), strict=True)
            headers = next(reader)
            rows = []
            for row in reader:
                rows.append(row)
                if len(rows) > MAX_ROWS:
                    raise RetrievalError('CSV exceeds row limit')
            table = make_table(url, 'CSV dataset', headers, rows)
            return [table] if table else []
        except (csv.Error, StopIteration):
            raise RetrievalError('Invalid CSV') from None
    if not ('html' in content_type.lower() or '<table' in text.lower()):
        return []
    parser = TableParser()
    parser.feed(text)
    result = []
    for caption, raw in parser.tables:
        grid, flags = expand(raw)
        # Without explicit headers the first row may be a data record. Never
        # promote that record into metadata sent to the selection model.
        if len(grid) < 2 or not flags[0]:
            continue
        count = 1
        while count < len(flags) and flags[count] and flags[0]:
            count += 1
        width = len(grid[count - 1])
        if any(len(row) != width for row in grid[:count]):
            continue
        headers = [' '.join(dict.fromkeys(row[i] for row in grid[:count] if row[i])) for i in range(width)]
        # Repeated all-header rows occur between sports-table sections.
        rows = [row for row, flag in zip(grid[count:], flags[count:]) if not flag]
        table = make_table(url, caption or parser.title, headers, rows)
        if table:
            result.append(table)
    return result


class Collector:
    def __init__(self, getter=None):
        self.getter = getter or http_get
        self.attempts = []
        self.tables = []
        self.visited = set()
        self.stop_reason = None

    def collect(self, urls):
        deadline = time.monotonic() + MAX_SECONDS
        for original in urls:
            url = original
            while True:
                if len(self.attempts) >= MAX_FETCHES:
                    self.stop_reason = 'request_limit'
                    return self.tables
                if time.monotonic() >= deadline:
                    self.stop_reason = 'time_limit'
                    return self.tables
                try:
                    url = public_url(url)
                except RetrievalError:
                    break
                if url in self.visited:
                    break
                self.visited.add(url)
                attempt = {'url': url, 'status': 'failed'}
                self.attempts.append(attempt)  # Charge before I/O, even on failure.
                try:
                    status, headers, body = self.getter(url, min(10, deadline - time.monotonic()))
                    attempt['status'] = str(status)
                    if status in (301, 302, 303, 307, 308):
                        url = urljoin(url, headers.get('location', ''))
                        continue
                    if status == 200:
                        if len(body) > MAX_BYTES:
                            raise RetrievalError('Response exceeds 2 MB')
                        found = parse_tables(url, headers.get('content-type', ''), body)
                        self.tables.extend(found[:MAX_TABLES - len(self.tables)])
                except Exception:
                    attempt['status'] = 'failed'
                break
            if len(self.tables) >= MAX_TABLES:
                self.stop_reason = 'table_limit'
                break
        return self.tables


def main():
    parser = argparse.ArgumentParser(description='Fetch public CSV/HTML tables, capped at 20 HTTP requests.')
    parser.add_argument('urls', nargs='+')
    parser.add_argument('--table', type=int, help='Table id to export; omit to list metadata')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    collector = Collector()
    tables = collector.collect(args.urls)
    if args.table is not None:
        if args.output is None or not 0 <= args.table < len(tables):
            parser.error('Choose a listed table id and provide --output')
        args.output.write_bytes(tables[args.table].csv_bytes())
    print(json.dumps({'tables': [table.metadata(i) for i, table in enumerate(tables)],
                      'requests': collector.attempts, 'stop_reason': collector.stop_reason}))
    return 0 if tables else 1


if __name__ == '__main__':
    raise SystemExit(main())
