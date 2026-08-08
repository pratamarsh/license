"""Penyimpanan snapshot & post di SQLite.

Snapshot bersifat append-only sehingga riwayat pertumbuhan follower tetap utuh.
Post di-upsert berdasarkan post_id karena angka like/komentar berubah seiring waktu.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from .models import Post, Snapshot

DEFAULT_DB_PATH = "iglead.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT NOT NULL,
    captured_at         TEXT NOT NULL,
    followers_count     INTEGER NOT NULL,
    media_count         INTEGER NOT NULL,
    biography           TEXT DEFAULT '',
    profile_picture_url TEXT DEFAULT '',
    UNIQUE (username, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_user_time
    ON snapshots (username, captured_at DESC);

CREATE TABLE IF NOT EXISTS posts (
    post_id        TEXT PRIMARY KEY,
    username       TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    like_count     INTEGER NOT NULL DEFAULT 0,
    comments_count INTEGER NOT NULL DEFAULT 0,
    media_type     TEXT DEFAULT '',
    permalink      TEXT DEFAULT '',
    caption        TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_posts_user_time
    ON posts (username, timestamp DESC);
"""


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


@contextmanager
def connect(db_path: str | Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Buka koneksi SQLite dengan skema terpasang dan row akses by-name."""
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_snapshot(conn: sqlite3.Connection, snapshot: Snapshot) -> None:
    """Simpan snapshot. Snapshot dengan username+waktu identik diabaikan."""
    conn.execute(
        """
        INSERT OR IGNORE INTO snapshots
            (username, captured_at, followers_count, media_count,
             biography, profile_picture_url)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        snapshot.as_row(),
    )


def save_posts(conn: sqlite3.Connection, posts: Iterable[Post]) -> int:
    """Upsert daftar post; mengembalikan jumlah baris yang ditulis."""
    rows = [p.as_row() for p in posts]
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO posts
            (post_id, username, timestamp, like_count, comments_count,
             media_type, permalink, caption)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (post_id) DO UPDATE SET
            like_count     = excluded.like_count,
            comments_count = excluded.comments_count,
            media_type     = excluded.media_type,
            permalink      = excluded.permalink,
            caption        = excluded.caption
        """,
        rows,
    )
    return len(rows)


def _row_to_snapshot(row: sqlite3.Row) -> Snapshot:
    return Snapshot(
        username=row["username"],
        captured_at=_parse_dt(row["captured_at"]),
        followers_count=row["followers_count"],
        media_count=row["media_count"],
        biography=row["biography"] or "",
        profile_picture_url=row["profile_picture_url"] or "",
    )


def latest_snapshot(
    conn: sqlite3.Connection, username: str, as_of: datetime | None = None
) -> Snapshot | None:
    """Snapshot terbaru untuk akun, opsional dibatasi sampai waktu `as_of`."""
    if as_of is None:
        row = conn.execute(
            "SELECT * FROM snapshots WHERE username = ? "
            "ORDER BY captured_at DESC LIMIT 1",
            (username.lower(),),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM snapshots WHERE username = ? AND captured_at <= ? "
            "ORDER BY captured_at DESC LIMIT 1",
            (username.lower(), as_of.isoformat()),
        ).fetchone()
    return _row_to_snapshot(row) if row else None


def snapshot_at_or_before(
    conn: sqlite3.Connection, username: str, cutoff: datetime
) -> Snapshot | None:
    """Snapshot terakhir sebelum `cutoff`; jika tak ada, snapshot paling awal.

    Dipakai sebagai basis pembanding pertumbuhan follower. Fallback ke snapshot
    paling awal supaya database yang baru terisi beberapa hari tetap bisa
    menampilkan tren, meski rentangnya lebih pendek dari yang diminta.
    """
    row = conn.execute(
        "SELECT * FROM snapshots WHERE username = ? AND captured_at <= ? "
        "ORDER BY captured_at DESC LIMIT 1",
        (username.lower(), cutoff.isoformat()),
    ).fetchone()
    if row:
        return _row_to_snapshot(row)

    row = conn.execute(
        "SELECT * FROM snapshots WHERE username = ? "
        "ORDER BY captured_at ASC LIMIT 1",
        (username.lower(),),
    ).fetchone()
    return _row_to_snapshot(row) if row else None


def snapshot_history(conn: sqlite3.Connection, username: str) -> list[Snapshot]:
    """Seluruh snapshot akun, urut dari yang paling lama."""
    rows = conn.execute(
        "SELECT * FROM snapshots WHERE username = ? ORDER BY captured_at ASC",
        (username.lower(),),
    ).fetchall()
    return [_row_to_snapshot(r) for r in rows]


def posts_between(
    conn: sqlite3.Connection, username: str, start: datetime, end: datetime
) -> list[Post]:
    """Post milik akun dengan timestamp di rentang [start, end]."""
    rows = conn.execute(
        "SELECT * FROM posts WHERE username = ? AND timestamp >= ? "
        "AND timestamp <= ? ORDER BY timestamp DESC",
        (username.lower(), start.isoformat(), end.isoformat()),
    ).fetchall()
    return [
        Post(
            username=r["username"],
            post_id=r["post_id"],
            timestamp=_parse_dt(r["timestamp"]),
            like_count=r["like_count"],
            comments_count=r["comments_count"],
            media_type=r["media_type"] or "",
            permalink=r["permalink"] or "",
            caption=r["caption"] or "",
        )
        for r in rows
    ]


def tracked_usernames(conn: sqlite3.Connection) -> list[str]:
    """Semua akun yang punya minimal satu snapshot."""
    rows = conn.execute(
        "SELECT DISTINCT username FROM snapshots ORDER BY username"
    ).fetchall()
    return [r["username"] for r in rows]


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Ringkasan isi database untuk perintah `status`."""
    return {
        "accounts": conn.execute(
            "SELECT COUNT(DISTINCT username) AS n FROM snapshots"
        ).fetchone()["n"],
        "snapshots": conn.execute(
            "SELECT COUNT(*) AS n FROM snapshots"
        ).fetchone()["n"],
        "posts": conn.execute("SELECT COUNT(*) AS n FROM posts").fetchone()["n"],
    }
