import sqlite3

SCHEMA = """
create table if not exists obs (
    source text not null,
    metric text not null,
    date text not null,
    area text not null,
    value real,
    primary key (source, metric, date, area)
)
"""


SEEN = "create table if not exists seen (source text not null, url text not null, primary key (source, url))"


def connect(path):
    conn = sqlite3.connect(path, timeout=60)
    conn.execute(SCHEMA)
    conn.execute(SEEN)
    return conn


def seen(conn, source):
    return {u for (u,) in conn.execute("select url from seen where source = ?", (source,))}


def mark_seen(conn, source, url):
    with conn:
        conn.execute("insert or ignore into seen values (?, ?)", (source, url))


def put(conn, source, metric, day, values):
    with conn:
        conn.executemany(
            "insert or replace into obs values (?, ?, ?, ?, ?)",
            [(source, metric, day.isoformat(), area, value) for area, value in values.items()],
        )


def clear(conn, source):
    with conn:
        conn.execute("delete from obs where source = ?", (source,))
