from datetime import datetime, timezone

import pytest

from iglead.leaderboard import NEUTRAL_SCORE, normalise, score_accounts, summarise
from iglead.models import AccountMetrics

NOW = datetime(2024, 6, 1, tzinfo=timezone.utc)


def metrics(username, followers=10_000, er=2.0, growth=1.0, ipp=200.0, freq=3.0):
    return AccountMetrics(
        username=username,
        label=username,
        captured_at=NOW,
        followers=followers,
        media_count=100,
        posts_analyzed=10,
        avg_likes=ipp * 0.9,
        avg_comments=ipp * 0.1,
        interactions_per_post=ipp,
        engagement_rate=er,
        posting_frequency=freq,
        follower_growth_pct=growth,
        follower_growth_abs=int(followers * growth / 100),
    )


class TestNormalise:
    def test_maps_range_to_zero_hundred(self):
        assert normalise([1.0, 3.0, 5.0]) == [0.0, 50.0, 100.0]

    def test_identical_values_get_neutral_score(self):
        assert normalise([7.0, 7.0, 7.0]) == [NEUTRAL_SCORE] * 3

    def test_single_value_is_neutral(self):
        assert normalise([42.0]) == [NEUTRAL_SCORE]

    def test_empty_input(self):
        assert normalise([]) == []

    def test_handles_negative_values(self):
        assert normalise([-10.0, 0.0, 10.0]) == [0.0, 50.0, 100.0]


class TestScoreAccounts:
    def test_ranks_by_weighted_score(self):
        weights = {"engagement_rate": 1.0}
        ranked = score_accounts(
            [metrics("low", er=1.0), metrics("high", er=9.0), metrics("mid", er=5.0)],
            weights,
        )

        assert [r.username for r in ranked] == ["high", "mid", "low"]
        assert [r.rank for r in ranked] == [1, 2, 3]
        assert ranked[0].score == pytest.approx(100.0)
        assert ranked[-1].score == pytest.approx(0.0)

    def test_weights_change_the_winner(self):
        accounts = [
            metrics("big_reach", followers=500_000, er=0.5),
            metrics("high_er", followers=10_000, er=8.0),
        ]

        by_engagement = score_accounts(accounts, {"engagement_rate": 1.0})
        by_size = score_accounts(accounts, {"followers": 1.0})

        assert by_engagement[0].username == "high_er"
        assert by_size[0].username == "big_reach"

    def test_component_scores_recorded_for_each_weight(self):
        weights = {"engagement_rate": 0.5, "followers": 0.5}
        ranked = score_accounts([metrics("a", er=1.0), metrics("b", er=4.0)], weights)

        assert set(ranked[0].component_scores) == {"engagement_rate", "followers"}

    def test_score_stays_within_bounds(self):
        weights = {"engagement_rate": 0.6, "followers": 0.4}
        ranked = score_accounts(
            [metrics(f"a{i}", er=i * 1.5, followers=i * 3000) for i in range(1, 6)],
            weights,
        )

        assert all(0.0 <= r.score <= 100.0 for r in ranked)

    def test_scores_are_monotonically_non_increasing(self):
        weights = {"engagement_rate": 0.5, "follower_growth_pct": 0.5}
        ranked = score_accounts(
            [metrics(f"a{i}", er=i, growth=6 - i) for i in range(1, 6)], weights
        )
        scores = [r.score for r in ranked]

        assert scores == sorted(scores, reverse=True)

    def test_empty_input_returns_empty(self):
        assert score_accounts([], {"engagement_rate": 1.0}) == []

    def test_single_account_gets_rank_one(self):
        ranked = score_accounts([metrics("solo")], {"engagement_rate": 1.0})

        assert len(ranked) == 1
        assert ranked[0].rank == 1
        assert ranked[0].score == pytest.approx(NEUTRAL_SCORE)

    def test_tie_broken_by_engagement_then_followers(self):
        # Bobot nol pada semua metrik membuat skor identik, sehingga urutan
        # ditentukan sepenuhnya oleh aturan pemutus seri.
        weights = {"posting_frequency": 1.0}
        ranked = score_accounts(
            [metrics("a", er=2.0, freq=3.0), metrics("b", er=5.0, freq=3.0)], weights
        )

        assert ranked[0].username == "b"

    def test_missing_growth_does_not_crash_scoring(self):
        account = metrics("a")
        account.follower_growth_pct = None
        ranked = score_accounts([account, metrics("b", growth=5.0)], {"follower_growth_pct": 1.0})

        assert ranked[0].username == "b"
        assert len(ranked) == 2


class TestSummarise:
    def test_reports_totals_and_leaders(self):
        ranked = score_accounts(
            [
                metrics("a", followers=10_000, er=1.0, growth=1.0),
                metrics("b", followers=30_000, er=9.0, growth=7.0),
            ],
            {"engagement_rate": 1.0},
        )
        summary = summarise(ranked)

        assert summary["accounts"] == 2
        assert summary["total_followers"] == 40_000
        assert summary["avg_engagement_rate"] == pytest.approx(5.0)
        assert summary["leader"].username == "b"
        assert summary["best_engagement"].username == "b"
        assert summary["fastest_growing"].username == "b"

    def test_empty_leaderboard(self):
        summary = summarise([])

        assert summary["accounts"] == 0
        assert summary["leader"] is None
        assert summary["fastest_growing"] is None

    def test_fastest_growing_is_none_when_no_baseline_exists(self):
        account = metrics("a")
        account.follower_growth_pct = None
        summary = summarise(score_accounts([account], {"engagement_rate": 1.0}))

        assert summary["fastest_growing"] is None
        assert summary["leader"] is not None
