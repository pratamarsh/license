"""Impor data manual dari CSV.

Berguna kalau kompetitor bukan akun Business (tidak terbaca business_discovery)
atau saat Anda ingin mengisi data historis hasil pencatatan manual.

Dua bentuk file didukung dan dikenali otomatis dari headernya:

snapshots.csv
    username,captured_at,followers_count,media_count[,biography]

posts.csv
    username,post_id,timestamp,like_count,comments_count[,media_type,permalink]
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import storage
from .models import Post, Snapshot

SNAPSHOT_REQUIRED = {"username", "followers_count"}
POST_REQUIRED = {"username", "post_id"}


class ImportError_(Exception):
    """File CSV tidak sesuai format yang diharapkan."""


def _parse_dt(value: str, fallback: datetime | None = None) -> datetime:
    """Terima ISO-8601 atau 'YYYY-MM-DD'; hasil selalu timezone-aware UTC."""
    text = (value or "").strip()
    if not text:
        if fallback is not None:
            return fallback
        raise ImportError_("kolom tanggal kosong dan tidak ada nilai default")

    normalised = text.replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        else:
            raise ImportError_(f"format tanggal tidak dikenali: {value!r}") from None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_int(value: str, field: str, row_number: int) -> int:
    text = (value or "").strip().replace(",", "").replace(".", "")
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        raise ImportError_(
            f"baris {row_number}: kolom '{field}' bukan angka: {value!r}"
        ) from None


def _clean_username(value: str) -> str:
    return (value or "").strip().lstrip("@")


def detect_kind(headers: set[str]) -> str:
    """Tentukan jenis file dari kolom yang tersedia."""
    if POST_REQUIRED.issubset(headers) or "like_count" in headers:
        return "posts"
    if SNAPSHOT_REQUIRED.issubset(headers) or "followers" in headers:
        return "snapshots"
    raise ImportError_(
        "header CSV tidak dikenali. Wajib ada 'username' plus "
        "'followers_count' (snapshot) atau 'post_id'/'like_count' (post)."
    )


def import_csv(
    conn: sqlite3.Connection, path: str | Path, kind: str | None = None
) -> tuple[str, int]:
    """Impor satu file CSV. Mengembalikan (jenis, jumlah baris tersimpan)."""
    path = Path(path)
    if not path.exists():
        raise ImportError_(f"file tidak ditemukan: {path}")

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ImportError_(f"{path} kosong atau tanpa header")

        headers = {name.strip().lower() for name in reader.fieldnames if name}
        resolved = kind or detect_kind(headers)
        now = datetime.now(timezone.utc)
        written = 0

        if resolved == "snapshots":
            for line_number, raw in enumerate(reader, start=2):
                row = {(k or "").strip().lower(): (v or "") for k, v in raw.items()}
                username = _clean_username(row.get("username", ""))
                if not username:
                    continue
                storage.save_snapshot(
                    conn,
                    Snapshot(
                        username=username,
                        captured_at=_parse_dt(
                            row.get("captured_at") or row.get("date") or "", now
                        ),
                        followers_count=_to_int(
                            row.get("followers_count") or row.get("followers", ""),
                            "followers_count",
                            line_number,
                        ),
                        media_count=_to_int(
                            row.get("media_count") or row.get("posts", ""),
                            "media_count",
                            line_number,
                        ),
                        biography=row.get("biography", ""),
                    ),
                )
                written += 1
        else:
            batch: list[Post] = []
            for line_number, raw in enumerate(reader, start=2):
                row = {(k or "").strip().lower(): (v or "") for k, v in raw.items()}
                username = _clean_username(row.get("username", ""))
                post_id = (row.get("post_id") or "").strip()
                if not username or not post_id:
                    continue
                batch.append(
                    Post(
                        username=username,
                        post_id=post_id,
                        timestamp=_parse_dt(
                            row.get("timestamp") or row.get("date") or "", now
                        ),
                        like_count=_to_int(
                            row.get("like_count") or row.get("likes", ""),
                            "like_count",
                            line_number,
                        ),
                        comments_count=_to_int(
                            row.get("comments_count") or row.get("comments", ""),
                            "comments_count",
                            line_number,
                        ),
                        media_type=row.get("media_type", ""),
                        permalink=row.get("permalink", ""),
                        caption=row.get("caption", ""),
                    )
                )
            written = storage.save_posts(conn, batch)

    return resolved, written
