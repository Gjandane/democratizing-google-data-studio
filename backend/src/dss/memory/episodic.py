"""Episodic memory: chat persistence and retrieval by recency (this build) and relevance (FTS5)."""
import re

from dss.db import new_id, now

RECENT, TOP, MAX_TERMS = 12, 3, 32
STOPWORDS = frozenset("""
a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing don down during each either etc few for
from further get had has have having he her here hers herself him himself his how i if in into is
it its itself just let like me might more most must my myself no nor not now of off on once only or
other our ours ourselves out over own please same shall she should so some such than that the
their theirs them themselves then there these they this those through to too under until up us
very want was we were what when where which while who whom why will with would yes yet you your
yours yourself yourselves""".split())


def messages(db, build_id, limit=None):
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id,role,text,node,created_at FROM messages WHERE build_id=? ORDER BY rowid DESC LIMIT ?",
            (build_id, limit if limit is not None else -1)).fetchall()
    return [dict(row) for row in reversed(rows)]


def save(db, build_id, role, text, node=None, message_id=None):
    message = dict(id=message_id or new_id("m"), role=role, text=text, node=node, created_at=now())
    with db.connect() as conn:
        conn.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)",
                     (message["id"], build_id, role, text, node, message["created_at"]))
    return message


def fts_query(text):
    """OR of the input's distinct non-stopword terms, each a quoted FTS5 string; '' if none.

    Terms are letter/digit runs, so no FTS5 operator, column filter or quote survives.
    """
    terms = dict.fromkeys(term for term in re.findall(r"[^\W_]+", text.lower())
                          if len(term) > 1 and term not in STOPWORDS)
    return " OR ".join(f'"{term}"' for term in list(terms)[:MAX_TERMS])


def relevant(db, build_id, text, limit=TOP):
    """Top bm25 matches among other builds' messages, each with its date and build title."""
    query = fts_query(text)
    if not query:
        return []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT m.id,m.build_id,b.title AS build_title,m.role,m.text,m.node,m.created_at "
            "FROM messages_fts JOIN messages m ON m.rowid=messages_fts.rowid JOIN builds b ON b.id=m.build_id "
            "WHERE messages_fts MATCH ? AND m.build_id<>? ORDER BY bm25(messages_fts), m.rowid DESC LIMIT ?",
            (query, build_id, limit)).fetchall()
    return [dict(row, date=row["created_at"][:10]) for row in rows]


def merge(hits, recent):
    """Union deduped by id: relevance hits first, then recent messages."""
    seen, result = set(), []
    for message in [*hits, *recent]:
        if message["id"] not in seen:
            seen.add(message["id"])
            result.append(message)
    return result


def recall(db, build_id, user_input, *, query=None, recent=RECENT, top=TOP):
    """Relevant past-build messages, then this build's last `recent` messages before the input.

    `query` overrides the FTS text; an empty one means recency only.
    """
    history = [dict(message, build_id=build_id) for message in messages(db, build_id, recent + 1)]
    # The API saves a user turn before its run; that turn is the user input, not history.
    if history and history[-1]["role"] == "user" and history[-1]["text"] == user_input:
        history.pop()
    hits = relevant(db, build_id, user_input if query is None else query, top)
    return merge(hits, history[-recent:])
