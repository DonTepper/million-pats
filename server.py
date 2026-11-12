#!/usr/bin/env python3
"""Serve the site and a shared pat counter.

Production stores the count in Postgres (DATABASE_URL). One UPDATE ... RETURNING
statement is the atomic increment, so every visitor shares the same total and
restarts do not create a second counter. Local runs without DATABASE_URL use
data/pats.sqlite.
"""

import json
import os
import sqlite3
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "pats.sqlite"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
MAX_PER_REQUEST = 30
lock = threading.Lock()


def init_db():
    if DATABASE_URL:
        init_postgres()
    else:
        init_sqlite()


def init_sqlite():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pats (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    count INTEGER NOT NULL
                )
                """
            )
            conn.execute("INSERT OR IGNORE INTO pats (id, count) VALUES (1, 0)")
            conn.commit()
        finally:
            conn.close()


def init_postgres():
    import psycopg

    with psycopg.connect(DATABASE_URL, connect_timeout=15) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pats (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                count BIGINT NOT NULL
            )
            """
        )
        # Never replace a count that is already stored.
        conn.execute(
            "INSERT INTO pats (id, count) VALUES (1, 0) ON CONFLICT (id) DO NOTHING"
        )
        floor = os.environ.get("PAT_COUNT_FLOOR", "").strip()
        if floor.isdigit():
            conn.execute(
                "UPDATE pats SET count = GREATEST(count, %s) WHERE id = 1",
                (int(floor),),
            )
        conn.commit()


def read_count():
    if DATABASE_URL:
        import psycopg

        with psycopg.connect(DATABASE_URL, connect_timeout=15) as conn:
            row = conn.execute("SELECT count FROM pats WHERE id = 1").fetchone()
            return int(row[0] if row else 0)
    with lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute("SELECT count FROM pats WHERE id = 1").fetchone()
            return int(row[0] if row else 0)
        finally:
            conn.close()


def add_count(amount):
    amount = max(1, min(int(amount), MAX_PER_REQUEST))
    if DATABASE_URL:
        import psycopg

        with psycopg.connect(DATABASE_URL, connect_timeout=15) as conn:
            row = conn.execute(
                "UPDATE pats SET count = count + %s WHERE id = 1 RETURNING count",
                (amount,),
            ).fetchone()
            conn.commit()
            if row is None:
                raise RuntimeError("pat counter row is missing")
            return int(row[0])
    with lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE pats SET count = count + ? WHERE id = 1", (amount,))
            row = conn.execute("SELECT count FROM pats WHERE id = 1").fetchone()
            conn.commit()
            return int(row[0])
        finally:
            conn.close()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/pats":
            try:
                self.respond({"count": read_count()})
            except Exception:
                self.respond({"error": "counter unavailable"}, status=503)
            return
        if self.blocked(path):
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/pats":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        amount = 1
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
                amount = int(payload.get("count", 1))
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
                self.respond({"error": "bad request"}, status=400)
                return
        try:
            self.respond({"count": add_count(amount)})
        except Exception:
            self.respond({"error": "counter unavailable"}, status=503)

    def blocked(self, path):
        name = Path(path).name
        return (
            path.startswith("/data")
            or path.startswith("/api/")
            or name in {"server.py", "Procfile", "requirements.txt"}
        )

    def respond(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    init_db()
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"pat site on http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
