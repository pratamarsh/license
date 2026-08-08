"""Penyusunan peringkat dari metrik akun.

Skor komposit dihitung dengan normalisasi min-max per metrik ke skala 0-100,
lalu dijumlahkan berbobot. Normalisasi bersifat relatif terhadap kumpulan akun
yang sedang dibandingkan: skor 100 berarti terbaik di antara peserta, bukan
sempurna secara absolut.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .config import Config
from .metrics import collect_metrics
from .models import AccountMetrics, RankedAccount

#: Nilai netral saat seluruh peserta punya angka identik (termasuk kasus satu
#: peserta), sehingga tidak ada yang diuntungkan atau dirugikan.
NEUTRAL_SCORE = 50.0


def normalise(values: list[float]) -> list[float]:
    """Petakan deretan angka ke skala 0-100 secara min-max."""
    if not values:
        return []

    lowest, highest = min(values), max(values)
    spread = highest - lowest
    if spread <= 0:
        return [NEUTRAL_SCORE] * len(values)

    return [(v - lowest) / spread * 100.0 for v in values]


def score_accounts(
    metrics: list[AccountMetrics], weights: dict[str, float]
) -> list[RankedAccount]:
    """Beri skor dan peringkat pada sekumpulan akun."""
    if not metrics:
        return []

    normalised: dict[str, list[float]] = {
        name: normalise([m.metric(name) for m in metrics]) for name in weights
    }

    ranked: list[RankedAccount] = []
    for index, account in enumerate(metrics):
        components = {name: normalised[name][index] for name in weights}
        score = sum(components[name] * weight for name, weight in weights.items())
        ranked.append(
            RankedAccount(
                rank=0,  # diisi setelah pengurutan
                score=score,
                metrics=account,
                component_scores=components,
            )
        )

    # Urut skor menurun; seri diputus oleh engagement rate lalu jumlah follower.
    ranked.sort(
        key=lambda r: (r.score, r.metrics.engagement_rate, r.metrics.followers),
        reverse=True,
    )
    for position, entry in enumerate(ranked, start=1):
        entry.rank = position

    return ranked


def build_leaderboard(
    conn: sqlite3.Connection,
    config: Config,
    *,
    compare_as_of: datetime | None = None,
) -> tuple[list[RankedAccount], list[str]]:
    """Susun leaderboard terkini, opsional dengan pergerakan peringkat.

    `compare_as_of` menghitung ulang leaderboard menggunakan data sampai tanggal
    tersebut, lalu selisih posisinya dipasang di `rank_delta`.
    """
    metrics, missing = collect_metrics(conn, config)
    ranked = score_accounts(metrics, config.weights)

    if compare_as_of is not None and ranked:
        past_metrics, _ = collect_metrics(conn, config, as_of=compare_as_of)
        past_ranked = score_accounts(past_metrics, config.weights)
        past_positions = {r.username.lower(): r.rank for r in past_ranked}

        for entry in ranked:
            previous = past_positions.get(entry.username.lower())
            # Peringkat kecil = posisi bagus, jadi delta positif berarti naik.
            entry.rank_delta = None if previous is None else previous - entry.rank

    return ranked, missing


def summarise(ranked: list[RankedAccount]) -> dict[str, object]:
    """Angka ringkas untuk header laporan."""
    if not ranked:
        return {
            "accounts": 0,
            "total_followers": 0,
            "avg_engagement_rate": 0.0,
            "leader": None,
            "best_engagement": None,
            "fastest_growing": None,
        }

    with_growth = [
        r for r in ranked if r.metrics.follower_growth_pct is not None
    ]

    return {
        "accounts": len(ranked),
        "total_followers": sum(r.metrics.followers for r in ranked),
        "avg_engagement_rate": sum(r.metrics.engagement_rate for r in ranked)
        / len(ranked),
        "leader": ranked[0],
        "best_engagement": max(ranked, key=lambda r: r.metrics.engagement_rate),
        "fastest_growing": max(
            with_growth, key=lambda r: r.metrics.follower_growth_pct or 0.0
        )
        if with_growth
        else None,
    }
