"""Current chat persistence (cross-build retrieval is added in task 6.1)."""
from dss.db import new_id, now


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
