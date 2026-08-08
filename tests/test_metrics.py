from datetime import datetime, timedelta, timezone

import pytest

from iglead.metrics import _engagement_rate, _growth, _posting_frequency, compute_metrics
from iglead.models import Post, Snapshot

NOW = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)


def snap(followers=10_000, media=200, at=NOW, username="acme"):
    return Snapshot(
        username=username, captured_at=at, followers_count=followers, media_count=media
    )


def post(likes=100, comments=10, days_ago=1, post_id="p1", username="acme", media_type="IMAGE"):
    return Post(
        username=username,
        post_id=post_id,
        timestamp=NOW - timedelta(days=days_ago),
        like_count=likes,
        comments_count=comments,
        media_type=media_type,
        permalink=f"https://instagram.com/p/{post_id}/",
    )


class TestEngagementRate:
    def test_ratio_is_percentage_of_followers(self):
        assert _engagement_rate(250.0, 10_000) == pytest.approx(2.5)

    def test_zero_followers_does_not_divide_by_zero(self):
        assert _engagement_rate(500.0, 0) == 0.0

    def test_no_interactions_gives_zero(self):
        assert _engagement_rate(0.0, 10_000) == 0.0


class TestPostingFrequency:
    def test_converts_window_to_posts_per_week(self):
        assert _posting_frequency(12, 28) == pytest.approx(3.0)

    def test_handles_partial_week(self):
        assert _posting_frequency(2, 7) == pytest.approx(2.0)

    def test_zero_window_is_safe(self):
        assert _posting_frequency(5, 0) == 0.0


class TestGrowth:
    def test_computes_absolute_and_percentage(self):
        baseline = snap(followers=10_000, at=NOW - timedelta(days=30))
        delta, pct = _growth(snap(followers=11_500), baseline)
        assert delta == 1_500
        assert pct == pytest.approx(15.0)

    def test_negative_growth(self):
        baseline = snap(followers=10_000, at=NOW - timedelta(days=30))
        delta, pct = _growth(snap(followers=9_000), baseline)
        assert delta == -1_000
        assert pct == pytest.approx(-10.0)

    def test_no_baseline_returns_none(self):
        assert _growth(snap(), None) == (None, None)

    def test_baseline_not_older_than_current_is_rejected(self):
        # Baseline dengan waktu sama tidak boleh dianggap sebagai pembanding.
        assert _growth(snap(at=NOW), snap(at=NOW)) == (None, None)

    def test_zero_baseline_followers_gives_no_percentage(self):
        baseline = snap(followers=0, at=NOW - timedelta(days=30))
        delta, pct = _growth(snap(followers=500), baseline)
        assert delta == 500
        assert pct is None


class TestComputeMetrics:
    def test_aggregates_posts(self):
        posts = [
            post(likes=100, comments=10, post_id="a"),
            post(likes=300, comments=30, post_id="b", days_ago=5),
        ]
        result = compute_metrics(
            "acme", "Acme", snap(followers=10_000), posts, None, lookback_days=30
        )

        assert result.posts_analyzed == 2
        assert result.avg_likes == pytest.approx(200.0)
        assert result.avg_comments == pytest.approx(20.0)
        assert result.interactions_per_post == pytest.approx(220.0)
        assert result.engagement_rate == pytest.approx(2.2)
        assert result.posting_frequency == pytest.approx(2 / (30 / 7))

    def test_identifies_top_post_and_dominant_media_type(self):
        posts = [
            post(likes=100, comments=5, post_id="a", media_type="VIDEO"),
            post(likes=900, comments=50, post_id="b", media_type="VIDEO"),
            post(likes=200, comments=5, post_id="c", media_type="IMAGE"),
        ]
        result = compute_metrics("acme", "Acme", snap(), posts, None, lookback_days=30)

        assert result.top_post_interactions == 950
        assert result.top_post_permalink.endswith("/p/b/")
        assert result.best_media_type == "VIDEO"

    def test_account_without_posts_is_not_an_error(self):
        result = compute_metrics("acme", "Acme", snap(), [], None, lookback_days=30)

        assert result.posts_analyzed == 0
        assert result.avg_likes == 0.0
        assert result.engagement_rate == 0.0
        assert result.posting_frequency == 0.0
        assert result.top_post_permalink == ""

    def test_metric_accessor_treats_missing_growth_as_zero(self):
        result = compute_metrics("acme", "Acme", snap(), [], None, lookback_days=30)

        assert result.follower_growth_pct is None
        assert result.metric("follower_growth_pct") == 0.0
