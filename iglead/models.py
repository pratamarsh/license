"""Struktur data inti yang dipakai lintas modul."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Snapshot:
    """Potret profil sebuah akun pada satu waktu."""

    username: str
    captured_at: datetime
    followers_count: int
    media_count: int
    biography: str = ""
    profile_picture_url: str = ""

    def as_row(self) -> tuple:
        return (
            self.username.lower(),
            self.captured_at.isoformat(),
            self.followers_count,
            self.media_count,
            self.biography,
            self.profile_picture_url,
        )


@dataclass(frozen=True)
class Post:
    """Satu media milik akun, dengan angka interaksi saat ditarik."""

    username: str
    post_id: str
    timestamp: datetime
    like_count: int
    comments_count: int
    media_type: str = ""
    permalink: str = ""
    caption: str = ""

    @property
    def interactions(self) -> int:
        return self.like_count + self.comments_count

    def as_row(self) -> tuple:
        return (
            self.post_id,
            self.username.lower(),
            self.timestamp.isoformat(),
            self.like_count,
            self.comments_count,
            self.media_type,
            self.permalink,
            self.caption[:500],
        )


@dataclass
class AccountMetrics:
    """Metrik turunan satu akun untuk satu periode analisis."""

    username: str
    label: str
    captured_at: datetime
    followers: int
    media_count: int
    posts_analyzed: int
    avg_likes: float
    avg_comments: float
    interactions_per_post: float
    #: Persentase: interaksi rata-rata per post dibagi jumlah follower.
    engagement_rate: float
    #: Post per minggu di dalam rentang lookback.
    posting_frequency: float
    follower_growth_abs: int | None = None
    follower_growth_pct: float | None = None
    top_post_permalink: str = ""
    top_post_interactions: int = 0
    best_media_type: str = ""
    is_own: bool = False

    def metric(self, name: str) -> float:
        """Ambil nilai metrik skorable; None dianggap 0."""
        value = getattr(self, name, None)
        return float(value) if value is not None else 0.0


@dataclass
class RankedAccount:
    """Satu baris leaderboard: metrik + skor + posisi."""

    rank: int
    score: float
    metrics: AccountMetrics
    #: Skor per komponen setelah dinormalisasi ke 0-100.
    component_scores: dict[str, float]
    #: Perubahan posisi dibanding periode pembanding (positif = naik).
    rank_delta: int | None = None

    @property
    def username(self) -> str:
        return self.metrics.username

    @property
    def label(self) -> str:
        return self.metrics.label
