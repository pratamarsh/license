"""Perhitungan metrik turunan dari snapshot dan post mentah."""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timedelta

from . import storage
from .config import Config
from .models import AccountMetrics, Post, Snapshot


def _engagement_rate(interactions_per_post: float, followers: int) -> float:
    """Interaksi rata-rata per post sebagai persentase jumlah follower."""
    if followers <= 0:
        return 0.0
    return interactions_per_post / followers * 100.0


def _posting_frequency(post_count: int, window_days: int) -> float:
    """Rata-rata post per minggu di dalam rentang analisis."""
    if window_days <= 0:
        return 0.0
    return post_count / (window_days / 7.0)


def _growth(current: Snapshot, baseline: Snapshot | None) -> tuple[int | None, float | None]:
    """Selisih follower absolut dan persentase terhadap snapshot pembanding."""
    if baseline is None or baseline.captured_at >= current.captured_at:
        return None, None

    delta = current.followers_count - baseline.followers_count
    if baseline.followers_count <= 0:
        return delta, None
    return delta, delta / baseline.followers_count * 100.0


def compute_metrics(
    username: str,
    label: str,
    snapshot: Snapshot,
    posts: list[Post],
    baseline: Snapshot | None,
    lookback_days: int,
    *,
    is_own: bool = False,
) -> AccountMetrics:
    """Rakit AccountMetrics dari data mentah satu akun."""
    count = len(posts)
    total_likes = sum(p.like_count for p in posts)
    total_comments = sum(p.comments_count for p in posts)

    avg_likes = total_likes / count if count else 0.0
    avg_comments = total_comments / count if count else 0.0
    interactions_per_post = avg_likes + avg_comments

    top_post = max(posts, key=lambda p: p.interactions, default=None)
    media_types = Counter(p.media_type for p in posts if p.media_type)
    growth_abs, growth_pct = _growth(snapshot, baseline)

    return AccountMetrics(
        username=username,
        label=label,
        captured_at=snapshot.captured_at,
        followers=snapshot.followers_count,
        media_count=snapshot.media_count,
        posts_analyzed=count,
        avg_likes=avg_likes,
        avg_comments=avg_comments,
        interactions_per_post=interactions_per_post,
        engagement_rate=_engagement_rate(interactions_per_post, snapshot.followers_count),
        posting_frequency=_posting_frequency(count, lookback_days),
        follower_growth_abs=growth_abs,
        follower_growth_pct=growth_pct,
        top_post_permalink=top_post.permalink if top_post else "",
        top_post_interactions=top_post.interactions if top_post else 0,
        best_media_type=media_types.most_common(1)[0][0] if media_types else "",
        is_own=is_own,
    )


def metrics_for_account(
    conn: sqlite3.Connection,
    username: str,
    config: Config,
    *,
    as_of: datetime | None = None,
) -> AccountMetrics | None:
    """Hitung metrik satu akun dari database. None bila belum ada snapshot.

    `as_of` memungkinkan rekonstruksi leaderboard pada tanggal lampau, yang
    dipakai fitur perbandingan peringkat.

    Rentang analisis post ditambatkan ke waktu snapshot, bukan ke jam sekarang,
    supaya angka engagement tetap konsisten kalau `rank` dijalankan beberapa
    hari setelah `fetch` terakhir.
    """
    snapshot = storage.latest_snapshot(conn, username, as_of=as_of)
    if snapshot is None:
        return None

    reference = snapshot.captured_at
    window_start = reference - timedelta(days=config.lookback_days)
    posts = storage.posts_between(conn, username, window_start, reference)

    baseline_cutoff = snapshot.captured_at - timedelta(days=config.growth_window_days)
    baseline = storage.snapshot_at_or_before(conn, username, baseline_cutoff)

    return compute_metrics(
        username=username,
        label=config.label_for(username),
        snapshot=snapshot,
        posts=posts,
        baseline=baseline,
        lookback_days=config.lookback_days,
        is_own=bool(config.own_account)
        and username.lower() == config.own_account.lower(),
    )


def collect_metrics(
    conn: sqlite3.Connection,
    config: Config,
    *,
    as_of: datetime | None = None,
) -> tuple[list[AccountMetrics], list[str]]:
    """Hitung metrik untuk semua akun di config.

    Mengembalikan (metrik yang berhasil, username yang datanya belum ada).
    """
    found: list[AccountMetrics] = []
    missing: list[str] = []

    for username in config.all_usernames:
        result = metrics_for_account(conn, username, config, as_of=as_of)
        if result is None:
            missing.append(username)
        else:
            found.append(result)

    return found, missing
