"""Bounded CSV intake and aggregate-only BigQuery source profiles."""
import csv
import io
from hashlib import sha256
import math
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit

from google.auth.transport.requests import AuthorizedSession
import google.auth
from google.cloud import bigquery

from dss.harness.guardrails import RunError

MAX_SOURCE_BYTES = 100 * 1024 * 1024
csv.field_size_limit(MAX_SOURCE_BYTES)
# GenerationSpec column type -> declared BigQuery type (contracts/synthetic-data.md). NUMERIC keeps
# the generator's fixed-scale decimals exact (<=6 places, |x| <= 10^12).
SYNTHETIC_TYPES = {"integer": "INTEGER", "number": "NUMERIC", "string": "STRING", "boolean": "BOOLEAN", "date": "DATE"}


def invalid(reason):
    return RunError("invalid_source", "Source could not be loaded", 422, {"reason": reason})


def snake_names(names):
    used, result = set(), []
    for name in names:
        base = re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()).strip("_") or "column"
        if base[0].isdigit() or base.startswith(("table_", "file_", "partition")):
            base = "col_" + base
        base = base[:280]
        candidate, n = base, 2
        while candidate in used:
            candidate, n = f"{base}_{n}", n + 1
        used.add(candidate)
        result.append(candidate)
    return result


def is_date(value):
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        date.fromisoformat(value)
        return True
    except ValueError:
        for fmt in ("%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y"):
            try:
                datetime.strptime(value, fmt)
                return True
            except ValueError:
                pass
    return False


def scalar_type(value):
    if value.lower() in ("true", "false"):
        return "BOOLEAN"
    if len(value) <= 20 and re.fullmatch(r"[+-]?\d+", value) and -(2**63) <= int(value) < 2**63:
        return "INTEGER"
    try:
        if Decimal(value).is_finite() and math.isfinite(float(value)):
            return "FLOAT"
    except InvalidOperation:
        pass
    # Only ISO dates are loaded as DATE; other date formats stay STRING/date_like.
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        date.fromisoformat(value)
        return "DATE"
    except ValueError:
        pass
    return "STRING"


def prepare_csv(content):
    if len(content) > MAX_SOURCE_BYTES:
        raise invalid("File exceeds 100 MB")
    try:
        text, encoding = content.decode("utf-8-sig"), "UTF-8"
    except UnicodeDecodeError:
        text, encoding = content.decode("latin-1"), "ISO-8859-1"
    if "\x00" in text:
        raise invalid("CSV contains NUL bytes")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        if not header:
            raise invalid("CSV is empty or missing a header")
        names = snake_names(header)
        types, count = [None] * len(names), 0
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(names)
        for row in reader:
            if not row or not any(value.strip() for value in row):
                continue
            if len(row) != len(names):
                raise invalid("CSV rows must have the same number of columns as the header")
            for i, value in enumerate(row):
                if value == "":
                    continue
                found = scalar_type(value)
                previous = types[i]
                types[i] = (found if previous is None else previous if previous == found else
                            "FLOAT" if {previous, found} <= {"INTEGER", "FLOAT"} else "STRING")
            writer.writerow(row)
            count += 1
        if not count:
            raise invalid("CSV has zero data rows")
        schema = [bigquery.SchemaField(name, kind or "STRING") for name, kind in zip(names, types)]
        return output.getvalue().encode("utf-8"), schema, encoding
    except (csv.Error, OverflowError, ValueError):
        raise invalid("Malformed CSV") from None


def table_uri(uri):
    if not re.fullmatch(r"[a-z][a-z0-9-]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_]+", uri):
        raise invalid("Expected project.dataset.table")
    return uri


def gcs_uri(uri):
    try:
        parsed = urlsplit(uri)
    except ValueError:
        raise invalid("Expected gs://bucket/path.csv for one CSV object") from None
    if (parsed.scheme != "gs" or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", parsed.netloc)
            or not parsed.path.lower().endswith(".csv") or parsed.query or parsed.fragment
            or any(c in parsed.path for c in "*?\r\n")):
        raise invalid("Expected gs://bucket/path.csv for one CSV object")
    return parsed.netloc, parsed.path.lstrip("/")


def quoted(name):
    # BigQuery flexible field names may contain punctuation. Escape before quoting.
    return "`" + name.replace("\\", "\\\\").replace("`", "\\`") + "`"


class BigQuery:
    def __init__(self, config, *, client=None, storage_session=None):
        self.config = config
        self.client = client or bigquery.Client(project=config.gcp_project_id, location=config.bq_location)
        self.storage_session = storage_session
        self.gcs_generations = {}

    def ensure_dataset(self):
        dataset = bigquery.Dataset(f"{self.config.gcp_project_id}.{self.config.bq_dataset}")
        dataset.location = self.config.bq_location
        self.client.create_dataset(dataset, exists_ok=True, timeout=30)

    def dry_run(self, sql):
        job = self.client.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False),
                                location=self.config.bq_location)
        job.result(timeout=30)
        return job.schema

    def create_view(self, table, sql):
        self.ensure_dataset()
        self.client.query(f"CREATE VIEW {quoted(table_uri(table))} AS\n{sql}",
                          job_id=self.view_job_id(table), location=self.config.bq_location).result(timeout=120)

    @staticmethod
    def view_job_id(table):
        return 'dss_view_' + sha256(table.encode()).hexdigest()

    def delete_view(self, table):
        return self._delete_after_job(self.view_job_id(table), table)

    @staticmethod
    def load_job_id(table):
        return 'dss_load_' + sha256(table.encode()).hexdigest()

    def load_typed_csv(self, table, path, columns):
        """Load a generated CSV with its declared schema; return the table's row count.

        Unlike load_csv this never rewrites the file (no prepare_csv): header names and every
        record, including all-empty ones, reach BigQuery. No autodetect; the empty field is the
        explicit null marker so all-null columns keep their declared type.
        """
        self.ensure_dataset()
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV, autodetect=False, skip_leading_rows=1,
            schema=[bigquery.SchemaField(name, SYNTHETIC_TYPES[kind], mode="NULLABLE") for name, kind in columns],
            allow_quoted_newlines=True, encoding="UTF-8", write_disposition="WRITE_EMPTY", max_bad_records=0)
        config.null_marker = ""
        with open(path, "rb") as handle:
            job = self.client.load_table_from_file(handle, table, job_config=config,
                                                   job_id=self.load_job_id(table), timeout=30)
        job.result(timeout=120)
        return self.client.get_table(table, timeout=30).num_rows

    def delete_loaded_table(self, table, *, fence_missing=False):
        return self._delete_after_job(self.load_job_id(table), table, fence_missing=fence_missing)

    def _delete_after_job(self, job_id, table, *, fence_missing=False):
        # A timed-out result() may still be executing in BigQuery. Keep ownership
        # until its deterministic job is terminal, then remove the table.
        try:
            job = self.client.get_job(job_id, location=self.config.bq_location, timeout=30)
        except Exception as exc:
            if getattr(exc, 'code', None) == 404:
                if not fence_missing:
                    self.client.delete_table(table_uri(table), not_found_ok=True, timeout=30)
                    return False  # Submission may have been accepted but not observed yet.
                # A no-table query claims the SAME job identity as the load. Either
                # it wins and a delayed load cannot start, or the load wins (409)
                # and we reconcile that job below. Absence alone is not a fence.
                try:
                    job = self.client.query('SELECT 1', job_id=job_id, location=self.config.bq_location,
                                            timeout=30, job_retry=None)
                except Exception as conflict:
                    if getattr(conflict, 'code', None) != 409:
                        raise
                    job = self.client.get_job(job_id, location=self.config.bq_location, timeout=30)
            else:
                raise
        if not job.done(timeout=30):
            job.cancel(timeout=30)
            try:
                job.result(timeout=30)
            except Exception:
                if not job.done(timeout=30):
                    raise
        self.client.delete_table(table_uri(table), not_found_ok=True, timeout=30)
        return True

    def aggregate(self, sql):
        """Execute a renderer-built, bounded aggregate query (never sent to an LLM)."""
        return [dict(row) for row in self.client.query(
            sql, location=self.config.bq_location, timeout=10).result(timeout=10)]

    def download_gcs(self, uri):
        bucket, name = gcs_uri(uri)
        session = self.storage_session
        owned = session is None
        if owned:
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            session = AuthorizedSession(credentials)
        try:
            url = f"https://storage.googleapis.com/storage/v1/b/{quote(bucket, safe='')}/o/{quote(name, safe='')}"
            with session.get(url, timeout=30) as response:
                response.raise_for_status()
                metadata = response.json()
            if int(metadata["size"]) > MAX_SOURCE_BYTES:
                raise invalid("File exceeds 100 MB")
            chunks, size = [], 0
            with session.get(url, params={"alt": "media", "generation": metadata["generation"]}, stream=True, timeout=30) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > MAX_SOURCE_BYTES:
                        raise invalid("File exceeds 100 MB")
                    chunks.append(chunk)
            self.gcs_generations[uri] = metadata["generation"]
            return b"".join(chunks)
        finally:
            if owned:
                session.close()

    def current_generation(self, uri):
        bucket, name = gcs_uri(uri)
        session = self.storage_session
        owned = session is None
        if owned:
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            session = AuthorizedSession(credentials)
        try:
            url = f"https://storage.googleapis.com/storage/v1/b/{quote(bucket, safe='')}/o/{quote(name, safe='')}"
            with session.get(url, timeout=30) as response:
                response.raise_for_status()
                return response.json()["generation"]
        finally:
            if owned:
                session.close()

    def check_generation(self, uri):
        if uri not in self.gcs_generations or self.current_generation(uri) != self.gcs_generations[uri]:
            raise invalid("GCS object changed during intake; retry with a stable object")

    def load_csv(self, table, content, *, uri=None):
        normalized, schema, encoding = prepare_csv(content)
        self.ensure_dataset()
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV, autodetect=not bool(uri), schema=schema,
            skip_leading_rows=1, allow_quoted_newlines=True,
            encoding=encoding if uri else "UTF-8", write_disposition="WRITE_EMPTY")
        if uri:
            # GCS retains its original header. BigQuery forbids POSITION with
            # autodetect, so use the schema inferred from the full validated CSV.
            config.source_column_match = "POSITION"
            self.check_generation(uri)
            job = self.client.load_table_from_uri(uri, table, job_config=config, timeout=30)
        else:
            job = self.client.load_table_from_file(io.BytesIO(normalized), table, job_config=config, timeout=30)
        job.result(timeout=120)
        if uri:
            # A mutable URI cannot pin a BigQuery load to an object generation.
            # Accept its result only if the validated generation remained current
            # through job completion; otherwise no Source/profile is persisted.
            self.check_generation(uri)

    def profile(self, table):
        from dss.data.profile import profile_table
        return profile_table(self, table)


def public_source(source):
    return {**source, "columns": [{key: col[key] for key in ("name", "type", "sample")} for col in source["columns"]]}
