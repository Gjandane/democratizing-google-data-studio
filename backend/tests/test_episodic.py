"""Episodic retrieval: this build's recent messages plus FTS5 relevance over other builds."""
import pytest
from dss.db import Database, new_id, now
from dss.memory import episodic


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "dss.sqlite")
    database.initialize()
    return database


def build(db, title):
    build_id = new_id("b")
    with db.connect() as conn:
        conn.execute("INSERT INTO builds(id,title,archetype,mode,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                     (build_id, title, "executive", "data", "interview", now(), now()))
    return build_id


def add(db, build_id, text, role="user", created_at=None):
    message_id = new_id("m")
    with db.connect() as conn:
        conn.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)",
                     (message_id, build_id, role, text, None, created_at or now()))
    return message_id


def test_similar_old_and_dissimilar_recent_both_come_back(db):
    current, past = build(db, "Current"), build(db, "Regional sales review")
    similar = add(db, past, "Compare quarterly revenue by region for the sales director", created_at="2025-03-01T10:00:00Z")
    add(db, past, "Use a dark theme with large logos", role="assistant")
    own_old = add(db, current, "Quarterly revenue by region matters most")  # outside the recency window
    recent = [add(db, current, f"Filler turn {i} about colours", role="assistant" if i % 2 else "user") for i in range(12)]
    add(db, current, "Show quarterly revenue by region")  # saved by the API before the run
    recalled = episodic.recall(db, current, "Show quarterly revenue by region")
    assert [m["id"] for m in recalled] == [similar, *recent]
    hit = recalled[0]
    assert hit["date"] == "2025-03-01" and hit["build_title"] == "Regional sales review" and hit["build_id"] == past
    assert own_old not in [m["id"] for m in recalled]
    assert all(m["build_id"] == current for m in recalled[1:])
    assert len({m["id"] for m in recalled}) == len(recalled)


def test_top_three_by_bm25_from_other_builds_only(db):
    current, other = build(db, "Current"), build(db, "Other")
    for i in range(10):
        add(db, other, f"Unrelated filler {i} about fonts")
    best = add(db, other, "revenue region margin trend")
    second = add(db, other, "revenue region")
    third = add(db, other, "revenue")
    add(db, current, "revenue region margin")
    hits = episodic.relevant(db, current, "What revenue, region and margin?")
    assert [h["id"] for h in hits] == [best, second, third]


def test_merge_dedupes_by_id_relevance_first():
    hits = [{"id": "m1"}, {"id": "m2"}]
    recent = [{"id": "m2"}, {"id": "m3"}, {"id": "m1"}]
    assert [m["id"] for m in episodic.merge(hits, recent)] == ["m1", "m2", "m3"]


def test_query_terms_are_quoted_without_stopwords():
    assert episodic.fts_query('Show the revenue "by" region*; REVENUE, order_date') == \
        '"show" OR "revenue" OR "region" OR "order" OR "date"'


@pytest.mark.parametrize("text", [
    'revenue" OR "x', '"', '*', 'NEAR(revenue region, 2)', 'revenue -region', 'text:revenue', '(revenue',
    'revenue^', 'AND', 'OR NOT', '{revenue}', "'; DROP TABLE messages; --", 'rev*nue + re:gion', 'région café',
    'revenue\x00region'])
def test_fts_special_characters_do_not_raise(db, text):
    current, other = build(db, "Current"), build(db, "Other")
    add(db, other, "Revenue by region")
    episodic.recall(db, current, text)
    assert len(episodic.recall(db, current, text + " revenue")) == 1


@pytest.mark.parametrize("text", ["", "   ", "?!", "and the of", "a I"])
def test_empty_query_means_recency_only(db, text):
    current, other = build(db, "Current"), build(db, "Other")
    add(db, other, "and the of a I")
    mine = add(db, current, "Earlier turn")
    assert episodic.fts_query(text) == ""
    assert [m["id"] for m in episodic.recall(db, current, text)] == [mine]


def test_query_override_and_recent_limit(db):
    current, other = build(db, "Current"), build(db, "Other")
    add(db, other, "Revenue by region")
    ids = [add(db, current, f"Turn {i}") for i in range(15)]
    recalled = episodic.recall(db, current, "Revenue by region", query="")
    assert [m["id"] for m in recalled] == ids[-12:]
    assert [m["id"] for m in episodic.recall(db, current, "Revenue", recent=2)][1:] == ids[-2:]


def test_terms_match_the_tokenizer_folding(db):
    current, other = build(db, "Current"), build(db, "Other")
    hit = add(db, other, "Umsatz pro Straße")
    assert [h["id"] for h in episodic.relevant(db, current, "STRASSE straße")] == [hit]
