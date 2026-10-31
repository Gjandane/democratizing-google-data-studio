"""Share data (api.md 3.4/3.5, recipe.md 1.4): POST /run exports the view as one CSV, BigQuery stubbed."""
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
from types import SimpleNamespace

from fastapi.testclient import TestClient
from google.cloud.bigquery.table import Row
from jsonschema import Draft202012Validator
import pytest

from dss.config import Config
from dss.data import share
from dss.main import create_app
from dss.recipe.compiler import compile_recipe, share_header
from dss.spec.models import DashboardSpec
from fakes import fake_models, ready_fixture
from test_agent_server import CODE, TOKENS, auth, claim, finish, make_build, settle, ticket
from test_recipe_contract import SCHEMA

BUCKET = "test-dss-share"
HEX = re.compile(r"^[0-9a-f]{32}$")
NAMES = ["day", "moment", "stamp", "region", "revenue", "ratio", "units", "active", "note"]
ROWS = [
    (date(2026, 3, 1), datetime(2026, 3, 1, 9, 5, 7, 123456), datetime(2026, 3, 1, 23, 30, tzinfo=timezone(timedelta(hours=-2))),
     "North, \"East\"", Decimal("1234.50"), 0.25, 3, True, None),
    (date(999, 1, 2), datetime(999, 1, 2, 0, 0), datetime(2026, 1, 1, tzinfo=timezone.utc), "line\nbreak", None, None, None, False, ""),
]
FORMATTED = [
    ["2026-03-01", "2026-03-01 09:05:07", "2026-03-02 01:30:00", "North, \"East\"", "1234.50", "0.25", "3", "true", ""],
    ["0999-01-02", "0999-01-02 00:00:00", "2026-01-01 00:00:00", "line\nbreak", "", "", "", "false", ""],
]


class Result:
    """A RowIterator stand-in: schema, an optional total_rows and lazily iterated rows."""

    def __init__(self, names, rows, total=None, types=None):
        types = types or {}
        self.schema = [SimpleNamespace(name=name, field_type=types.get(name, "STRING"), mode="NULLABLE")
                       for name in names]
        self.rows, self.total_rows = rows, total

    def __iter__(self):
        index = {name: i for i, name in enumerate(n.name for n in self.schema)}
        for values in self.rows():
            yield Row(values, index)


class Warehouse:
    def __init__(self, names=NAMES, rows=lambda: iter(ROWS), total=None, types=None):
        self.result, self.queries = Result(names, rows, total, types), []

    def __call__(self, config):  # the app's bigquery_factory
        return SimpleNamespace(config=config, client=self)

    def query(self, sql, **kwargs):
        self.queries.append(sql)
        return SimpleNamespace(result=lambda **_: self.result)


def unused(config):
    pytest.fail("BigQuery was queried without share data")


def app_for(tmp_path, factory, **config):
    return create_app(Config(data_dir=tmp_path, access_code=CODE, google_api_key="fake-google-key",
                             gcp_project_id="deployment", **config), model_lister=fake_models, bigquery_factory=factory)


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    """Agent mode with DSS_SHARE_BUCKET/DSS_SHARE_DIR; returns a function that opens the app."""
    monkeypatch.setenv("DSS_ENGINE_DRY_RUN", "1")
    share_dir = tmp_path / "share"
    share_dir.mkdir()
    def open_app(warehouse, **config):
        settings = dict(engine_mode="agent", share_bucket=BUCKET, share_dir=str(share_dir)) | config
        app = app_for(tmp_path / "data", warehouse, **settings)
        client = TestClient(app, headers={"X-DSS-Access-Code": CODE})
        client.__enter__()
        bid, folder = make_build(client, app, tmp_path / "data")
        opened.append(client)
        return client, app, bid, folder
    opened = []
    yield share_dir, open_app
    for client in opened:
        client.__exit__(None, None, None)


def job_recipe(client, bid):
    run_id = ticket(client, bid)["run_id"]
    claimed = claim(client, ticket(client, bid)["code"]).json()
    TOKENS[run_id] = {"X-DSS-Job-Token": claimed["job_token"]}
    response = client.get(f"/api/agent/jobs/{run_id}/files/recipe.jsonl", headers=auth(run_id))
    assert response.status_code == 200
    return run_id, response.content.decode("utf-8")


def exports(share_dir):
    return sorted(share_dir.iterdir())


def assert_nothing_started(client, app, bid, share_dir, response, status, code):
    assert response.status_code == status and response.json()["error"]["code"] == code, response.text
    assert exports(share_dir) == []
    assert client.get(f"/api/builds/{bid}/job").status_code == 404
    assert not app.state.agent_jobs.running and bid not in app.state.harness.active_builds
    build = client.get(f"/api/builds/{bid}").json()
    assert build["stage"] == "prototype" and build["versions"][0]["status"] != "building"


def test_cell_formats():
    assert [share.cell(v) for v in ROWS[0]] == FORMATTED[0]
    assert share.cell(datetime(2026, 5, 6, 7, 8, 9, tzinfo=timezone(timedelta(hours=8)))) == "2026-05-05 23:08:09"
    assert share.cell(10**20) == "100000000000000000000" and share.cell(1e-7) == "1e-07"


def test_run_exports_view_csv_with_gcs_header(hosted):
    share_dir, open_app = hosted
    warehouse = Warehouse()
    client, app, bid, folder = open_app(warehouse)
    canonical = (folder / "recipe.jsonl").read_text(encoding="utf-8")
    response = client.post(f"/api/builds/{bid}/run")
    assert response.status_code == 202, response.text
    assert warehouse.queries == ["SELECT * FROM `sample-project.dss_demo.small_sales`"]
    [target] = exports(share_dir)
    assert HEX.fullmatch(target.name) and [p.name for p in target.iterdir()] == ["data.csv"]
    with open(target / "data.csv", encoding="utf-8", newline="") as handle:
        assert list(csv.reader(handle)) == [NAMES, *FORMATTED]
    run_id, shipped = job_recipe(client, bid)
    header, ops = shipped.split("\n", 1)
    assert json.loads(header)["datasource"] == {
        "connector": "googleCloudStorage", "path_type": "FILE", "path": f"{BUCKET}/{target.name}/data.csv"}
    Draft202012Validator({**SCHEMA, "$ref": "#/$defs/header"}).validate(json.loads(header))
    assert ops == canonical.split("\n", 1)[1]  # the ops keep their bytes
    assert (folder / "recipe.jsonl").read_text(encoding="utf-8") == canonical  # the version keeps BigQuery
    assert json.loads(canonical.split("\n", 1)[0])["datasource"]["connector"] == "bigQuery"
    record = json.loads((folder / "share" / f"{run_id}.json").read_text(encoding="utf-8"))
    assert record == {"folder": target.name, "path": f"{BUCKET}/{target.name}/data.csv", "rows": 2,
                      "bytes": (target / "data.csv").stat().st_size}
    # A rerun exports fresh rows to a new folder.
    finish(client, run_id, 1)
    settle(client, app, bid)
    assert client.post(f"/api/builds/{bid}/run").status_code == 202
    first, second = exports(share_dir)
    assert {first, second} > {target} and len(warehouse.queries) == 2
    _, again = job_recipe(client, bid)
    other = (second if first == target else first).name
    assert json.loads(again.split("\n", 1)[0])["datasource"]["path"] == f"{BUCKET}/{other}/data.csv"


def test_over_a_million_rows_is_too_large(hosted):
    share_dir, open_app = hosted
    rows = lambda: ((i, "x") for i in range(share.MAX_ROWS + 1))
    client, app, bid, folder = open_app(Warehouse(["n", "s"], rows))
    response = client.post(f"/api/builds/{bid}/run")
    assert_nothing_started(client, app, bid, share_dir, response, 422, "share_too_large")
    assert not (folder / "share").exists() or not list((folder / "share").iterdir())


def test_known_total_and_byte_limit_stop_early(hosted, monkeypatch):
    share_dir, open_app = hosted
    def never():
        pytest.fail("rows were read although total_rows was over the limit")
    client, app, bid, _ = open_app(Warehouse(rows=never, total=share.MAX_ROWS + 1))
    assert_nothing_started(client, app, bid, share_dir, client.post(f"/api/builds/{bid}/run"), 422, "share_too_large")
    monkeypatch.setattr(share, "MAX_BYTES", 40)
    app.state.bigquery_factory = Warehouse()
    response = client.post(f"/api/builds/{bid}/run")
    assert_nothing_started(client, app, bid, share_dir, response, 422, "share_too_large")


def test_write_and_query_errors_fail_export(hosted, monkeypatch, caplog):
    share_dir, open_app = hosted
    def broken():
        yield ROWS[0]
        raise OSError("disk gone")
    client, app, bid, folder = open_app(Warehouse(rows=broken))
    assert_nothing_started(client, app, bid, share_dir, client.post(f"/api/builds/{bid}/run"), 503, "share_export_failed")
    def refused(source, target):
        raise PermissionError("rename refused")
    app.state.bigquery_factory = Warehouse()
    with monkeypatch.context() as patch:
        patch.setattr(share, "os", SimpleNamespace(replace=refused))  # the final rename fails
        assert_nothing_started(client, app, bid, share_dir, client.post(f"/api/builds/{bid}/run"), 503, "share_export_failed")
    # The record (written after the CSV) fails: the complete export goes too.
    (folder / "share").write_text("not a folder", encoding="utf-8")
    assert_nothing_started(client, app, bid, share_dir, client.post(f"/api/builds/{bid}/run"), 503, "share_export_failed")
    (folder / "share").unlink()
    # A share dir that is not mounted is never created.
    app.state.config.share_dir = str(share_dir / "missing")
    assert_nothing_started(client, app, bid, share_dir, client.post(f"/api/builds/{bid}/run"), 503, "share_export_failed")
    assert not (share_dir / "missing").exists()
    # A bucket the 1.4 header rejects fails before BigQuery is queried.
    app.state.config.share_dir, app.state.config.share_bucket = str(share_dir), "gs://Bad"
    app.state.bigquery_factory = unused
    assert_nothing_started(client, app, bid, share_dir, client.post(f"/api/builds/{bid}/run"), 503, "share_export_failed")
    assert "North" not in caplog.text and "disk gone" not in caplog.text


def test_agent_mode_without_share_vars_and_recipe_preview_keep_bigquery(hosted, tmp_path):
    share_dir, open_app = hosted
    client, app, bid, folder = open_app(unused, share_bucket="", share_dir="")
    assert client.get("/api/hosting").json()["share_data"] is False
    assert client.post(f"/api/builds/{bid}/run").status_code == 202
    _, shipped = job_recipe(client, bid)
    assert json.loads(shipped.split("\n", 1)[0])["datasource"]["connector"] == "bigQuery"
    assert shipped == (folder / "recipe.jsonl").read_text(encoding="utf-8")


def test_recipe_preview_never_exports(hosted):
    share_dir, open_app = hosted
    client, app, bid, folder = open_app(unused)
    assert client.get("/api/hosting").json()["share_data"] is True
    response = client.post(f"/api/builds/{bid}/recipe")
    assert response.status_code == 200, response.text
    assert json.loads((folder / "recipe.jsonl").read_text(encoding="utf-8").split("\n", 1)[0])["datasource"]["connector"] == "bigQuery"
    assert exports(share_dir) == [] and not (folder / "share").exists()


def test_local_mode_never_exports(tmp_path, monkeypatch):
    share_dir = tmp_path / "share"
    share_dir.mkdir()
    from dss.api import run
    launched = []
    monkeypatch.setattr(run, "launch", lambda *args: launched.append(args))
    app = app_for(tmp_path / "data", unused, share_bucket=BUCKET, share_dir=str(share_dir))
    with TestClient(app, headers={"X-DSS-Access-Code": CODE}) as client:
        bid, folder = make_build(client, app, tmp_path / "data")
        canonical = (folder / "recipe.jsonl").read_bytes()
        assert client.post(f"/api/builds/{bid}/run").status_code == 202
        app.state.engine_busy = False
    assert len(launched) == 1 and launched[0][-1] is None  # no job
    assert exports(share_dir) == [] and (folder / "recipe.jsonl").read_bytes() == canonical
    assert not (folder / "share").exists()


def test_restart_resumes_waiting_ticket_with_its_export(tmp_path, monkeypatch):
    monkeypatch.setenv("DSS_ENGINE_DRY_RUN", "1")
    share_dir = tmp_path / "share"
    share_dir.mkdir()
    hosted = dict(engine_mode="agent", share_bucket=BUCKET, share_dir=str(share_dir))
    app = app_for(tmp_path / "data", Warehouse(), **hosted)
    with TestClient(app, headers={"X-DSS-Access-Code": CODE}) as client:
        bid, _ = make_build(client, app, tmp_path / "data")
        assert client.post(f"/api/builds/{bid}/run").status_code == 202
        code = ticket(client, bid)["code"]
    [target] = exports(share_dir)
    app = app_for(tmp_path / "data", unused, **hosted)
    with TestClient(app, headers={"X-DSS-Access-Code": CODE}) as client:
        claimed = claim(client, code).json()
        run_id = claimed["job"]["run_id"]
        response = client.get(f"/api/agent/jobs/{run_id}/files/recipe.jsonl",
                              headers={"X-DSS-Job-Token": claimed["job_token"]})
        header = json.loads(response.content.decode("utf-8").split("\n", 1)[0])
        assert header["datasource"]["path"] == f"{BUCKET}/{target.name}/data.csv"
        TOKENS[run_id] = {"X-DSS-Job-Token": claimed["job_token"]}
        finish(client, run_id, 1)
        settle(client, app, bid)


# Sum-only numeric NULLs (api.md 3.5, task 30.1): release 4.6 finding H1.
SUMMED = ["region", "high_value_revenue", "high_value_order_id", "day", "active", "spare"]
SUMMED_ROWS = [("North", 1250.5, "o1", date(2026, 3, 1), True, None),
               ("South", None, None, None, None, None),
               ("East", None, None, None, None, 7.5)]
NUMERIC = ["FLOAT64", "FLOAT", "INT64", "INTEGER", "NUMERIC", "BIGNUMERIC"]


def chart(**fields):
    return {"id": "s005", "op": "add_chart", "chart_type": "bar", "component_id": "p1", "dimensions": [],
            "metrics": [], "options": {}, "title": "high_value_revenue", **fields}


def recipe_of(*ops):
    header = json.loads(THIN_HEADER)
    return "\n".join(json.dumps(line) for line in [header, *ops]) + "\n"


THIN_HEADER = compile_recipe(DashboardSpec.model_validate_json(
    Path("tests/data/thin_spec.json").read_text(encoding="utf-8")), 1).split(chr(10), 1)[0]
SUM = {"field": "high_value_revenue", "agg": "sum"}
SORTED = chart(dimensions=["region"], metrics=[SUM], sort={"field": "high_value_revenue", "order": "desc"})


def exported(tmp_path, recipe, kind="FLOAT64", types=None):
    """share.export over SUMMED rows; returns the CSV as {column: [cells]}."""
    share_dir = tmp_path / f"share-{len(list(tmp_path.iterdir()))}"
    share_dir.mkdir()
    folder = share_dir / "version"
    folder.mkdir()
    types = {"high_value_revenue": kind, "day": "DATE", "active": "BOOL", "spare": "FLOAT64"} | (types or {})
    warehouse = Warehouse(SUMMED, lambda: iter(SUMMED_ROWS), types=types)
    record = share.export(warehouse, SimpleNamespace(bq_location="US"), "p.d.v", recipe, folder, "r1", share_dir, BUCKET)
    with open(share_dir / record["folder"] / "data.csv", encoding="utf-8", newline="") as handle:
        header, *rows = list(csv.reader(handle))
    assert header == SUMMED
    return {name: [row[i] for row in rows] for i, name in enumerate(header)}


@pytest.mark.parametrize("kind", NUMERIC)
def test_sum_and_sort_only_numeric_nulls_are_zero(tmp_path, kind):
    count = chart(id="s006", metrics=[{"field": "high_value_order_id", "agg": "count_distinct"}])
    columns = exported(tmp_path, recipe_of(chart(metrics=[SUM]), SORTED, count), kind)
    assert columns["high_value_revenue"] == ["1250.5", "0", "0"]
    # Other rows and columns unchanged: STRING/DATE/BOOL NULLs and an unnamed numeric stay empty.
    assert columns["region"] == ["North", "South", "East"]
    assert columns["high_value_order_id"] == ["o1", "", ""]
    assert columns["day"] == ["2026-03-01", "", ""] and columns["active"] == ["true", "", ""]
    assert columns["spare"] == ["", "", "7.5"]


@pytest.mark.parametrize("other", [
    chart(metrics=[{"field": "high_value_revenue", "agg": agg}]) for agg in ("avg", "min", "max", "count", "count_distinct", "none")
] + [
    chart(dimensions=["high_value_revenue"]),
    chart(breakdown="high_value_revenue"),
    chart(date_dimension="high_value_revenue"),
    chart(options={"filter": {"field": "high_value_revenue"}}),
    {"id": "s009", "op": "add_control", "component_id": "c1", "control_type": "dropdown", "field": "high_value_revenue"},
])
def test_any_other_reference_keeps_null_empty(tmp_path, other):
    columns = exported(tmp_path, recipe_of(SORTED, {**other, "id": "s009"}))
    assert columns["high_value_revenue"] == ["1250.5", "", ""]


def test_non_numeric_unnamed_and_sort_only_keep_null_empty(tmp_path):
    summed = chart(metrics=[{"field": name, "agg": "sum"} for name in ("high_value_order_id", "day", "active")])
    columns = exported(tmp_path, recipe_of(summed, chart(id="s006", sort={"field": "spare", "order": "asc"})))
    assert columns["high_value_order_id"] == ["o1", "", ""] and columns["day"] == ["2026-03-01", "", ""]
    assert columns["active"] == ["true", "", ""] and columns["spare"] == ["", "", "7.5"]
    assert exported(tmp_path, recipe_of())["high_value_revenue"] == ["1250.5", "", ""]  # no op names it
    columns = exported(tmp_path, recipe_of(chart(metrics=[SUM])), types={"high_value_revenue": "STRING"})
    assert columns["high_value_revenue"] == ["1250.5", "", ""]


def test_run_zero_fills_from_the_shipped_recipe(hosted):
    """End to end: the rule reads the job's compiled recipe, whose bytes it leaves alone."""
    share_dir, open_app = hosted
    types = {"revenue": "FLOAT64", "ratio": "FLOAT64", "units": "INT64", "region": "STRING"}
    client, app, bid, folder = open_app(Warehouse(types=types))
    spec = json.loads((folder / "spec.json").read_text(encoding="utf-8"))
    for component in spec["pages"][0]["components"]:  # sort the bar on its summed metric
        if component["id"] == "p1_regions":
            component["sort"] = {"field": "revenue", "order": "desc"}
    (folder / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    ready_fixture(app, bid, folder)  # the proof covers the edited spec
    assert client.post(f"/api/builds/{bid}/run").status_code == 202
    [target] = exports(share_dir)
    with open(target / "data.csv", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    # revenue is only summed and sorted on: 0; ratio and units are named by no op: empty.
    assert rows == [NAMES, FORMATTED[0], [*FORMATTED[1][:4], "0", "", "", "false", ""]]
    _, shipped = job_recipe(client, bid)
    canonical = (folder / "recipe.jsonl").read_text(encoding="utf-8")
    assert '"sort":{"field":"revenue","order":"desc"}' in canonical
    assert shipped == share_header(canonical, f"{BUCKET}/{target.name}/data.csv")
    from dss.agent.jobs import API_VERSION
    assert API_VERSION == "3.4"
