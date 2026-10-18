"""Code node: load sources, persist aggregate profiles, and write the OKF bundle."""
import json
from pathlib import Path

import yaml

from dss.data.bigquery import invalid, prepare_csv, public_source, snake_names
from dss.db import new_id, now


def write_doc(path, metadata, body):
    temporary = path.with_suffix(".tmp")
    temporary.write_text("---\n" + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True) + "---\n\n" + body, encoding="utf-8")
    temporary.replace(path)


def perform(db, build_id, payload):
    config = payload["config"]
    service = payload["factory"](config)
    loaded = []
    # Validate the entire batch before starting any BigQuery load.
    prepared = []
    with db.connect() as connection:
        version = connection.execute("SELECT current_version FROM builds WHERE id=?", (build_id,)).fetchone()[0]
    for item in payload["sources"]:
        item = dict(item)
        item["id"] = new_id("s")
        kind = item["kind"]
        if kind == "gcs":
            item["content"] = service.download_gcs(item["uri"])
        if kind != "bigquery":
            prepare_csv(item["content"])
            slug = snake_names([Path(item["name"]).stem])[0][:200]
            # Fresh identity also makes retries safe if a failed batch already
            # created a remote table before its SQLite transaction was saved.
            item["table"] = f'{config.gcp_project_id}.{config.bq_dataset}.src_{build_id}_{slug}_{item["id"][2:]}'
        else:
            item["table"] = item["uri"]
        prepared.append(item)
    for item in prepared:
        if item["kind"] != "bigquery":
            service.load_csv(item["table"], item["content"], uri=item.get("uri"))
        profile = service.profile(item["table"])
        if profile["row_count"] < 1:
            raise invalid("Source has zero data rows")
        loaded.append({"id": item["id"], "kind": item["kind"], "name": item["name"],
                       "bq_table": item["table"], **profile})
    with db.connect() as connection:
        existing = [{"id": row["id"], "kind": row["kind"], "name": row["name"], "bq_table": row["bq_table"],
                     "row_count": row["row_count"], "columns": json.loads(row["columns_json"])}
                    for row in connection.execute("SELECT * FROM sources WHERE build_id=? ORDER BY rowid", (build_id,))]
        docs = config.data_dir / "builds" / build_id / f"v{version}" / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        sources = existing + loaded
        write_doc(docs / "data-profile.md", {"type": "BigQuery Table", "title": "Data profile", "sources": sources},
                  "# Data profile\n\n" + "\n".join(f'- {source["name"]}: `{source["bq_table"]}` ({source["row_count"]} rows)' for source in sources) + "\n")
        if not (docs / "index.md").exists():
            write_doc(docs / "index.md", {"type": "Index", "title": "Build documents"}, "# Build documents\n\n- [Data profile](data-profile.md)\n")
        if not (docs / "log.md").exists():
            write_doc(docs / "log.md", {"type": "Log", "title": "Build log"}, "# Build log\n")
        for source in loaded:
            connection.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?)", (
                source["id"], build_id, source["kind"], source["name"], source["bq_table"], source["row_count"], json.dumps(source["columns"])))
        connection.execute("UPDATE builds SET updated_at=? WHERE id=?", (now(), build_id))
    return [public_source(source) for source in loaded]
