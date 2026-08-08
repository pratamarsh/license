from datetime import datetime, timedelta, timezone

import pytest

from iglead import storage
from iglead.config import ConfigError, load_config
from iglead.csv_io import ImportError_, detect_kind, import_csv
from iglead.metrics import metrics_for_account
from iglead.models import Post, Snapshot

NOW = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    with storage.connect(tmp_path / "test.db") as conn:
        yield conn


def snap(followers, days_ago=0, username="acme"):
    return Snapshot(
        username=username,
        captured_at=NOW - timedelta(days=days_ago),
        followers_count=followers,
        media_count=100,
    )


class TestStorage:
    def test_saves_and_reads_latest_snapshot(self, db):
        storage.save_snapshot(db, snap(1000, days_ago=10))
        storage.save_snapshot(db, snap(1200, days_ago=0))

        assert storage.latest_snapshot(db, "acme").followers_count == 1200

    def test_latest_snapshot_respects_as_of(self, db):
        storage.save_snapshot(db, snap(1000, days_ago=10))
        storage.save_snapshot(db, snap(1200, days_ago=0))

        past = storage.latest_snapshot(db, "acme", as_of=NOW - timedelta(days=5))
        assert past.followers_count == 1000

    def test_username_lookup_is_case_insensitive(self, db):
        storage.save_snapshot(db, Snapshot("AcMe", NOW, 500, 10))

        assert storage.latest_snapshot(db, "acme") is not None

    def test_duplicate_snapshot_is_ignored(self, db):
        storage.save_snapshot(db, snap(1000))
        storage.save_snapshot(db, snap(1000))

        assert storage.stats(db)["snapshots"] == 1

    def test_missing_account_returns_none(self, db):
        assert storage.latest_snapshot(db, "nobody") is None

    def test_baseline_falls_back_to_earliest_snapshot(self, db):
        # Hanya ada data 5 hari; permintaan baseline 30 hari harus tetap dapat
        # snapshot paling awal daripada gagal.
        storage.save_snapshot(db, snap(1000, days_ago=5))
        storage.save_snapshot(db, snap(1100, days_ago=0))

        baseline = storage.snapshot_at_or_before(db, "acme", NOW - timedelta(days=30))
        assert baseline.followers_count == 1000

    def test_posts_are_upserted_not_duplicated(self, db):
        post = Post("acme", "p1", NOW, like_count=10, comments_count=1)
        storage.save_posts(db, [post])
        storage.save_posts(db, [Post("acme", "p1", NOW, like_count=99, comments_count=5)])

        stored = storage.posts_between(db, "acme", NOW - timedelta(days=1), NOW)
        assert len(stored) == 1
        assert stored[0].like_count == 99

    def test_posts_filtered_by_window(self, db):
        storage.save_posts(
            db,
            [
                Post("acme", "old", NOW - timedelta(days=90), 10, 1),
                Post("acme", "new", NOW - timedelta(days=2), 20, 2),
            ],
        )

        recent = storage.posts_between(db, "acme", NOW - timedelta(days=30), NOW)
        assert [p.post_id for p in recent] == ["new"]

    def test_stats_and_tracked_usernames(self, db):
        storage.save_snapshot(db, snap(100, username="a"))
        storage.save_snapshot(db, snap(200, username="b"))
        storage.save_posts(db, [Post("a", "p1", NOW, 1, 1)])

        assert storage.stats(db) == {"accounts": 2, "snapshots": 2, "posts": 1}
        assert storage.tracked_usernames(db) == ["a", "b"]


class TestConfig:
    def _write(self, tmp_path, text, name="c.yml"):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_full_config(self, tmp_path):
        path = self._write(
            tmp_path,
            "own_account: mine\n"
            "competitors:\n"
            "  - username: a\n"
            "    label: Alpha\n"
            "  - b\n"
            "posts_limit: 10\n",
        )
        config = load_config(path)

        assert config.own_account == "mine"
        assert config.all_usernames == ["a", "b"]
        assert config.label_for("a") == "Alpha"
        assert config.label_for("b") == "b"
        assert config.posts_limit == 10

    def test_strips_at_sign_and_profile_urls(self, tmp_path):
        path = self._write(
            tmp_path,
            "competitors:\n  - '@handle'\n  - https://instagram.com/other/\n",
        )
        assert load_config(path).all_usernames == ["handle", "other"]

    def test_duplicate_competitors_removed(self, tmp_path):
        path = self._write(tmp_path, "competitors:\n  - a\n  - '@a'\n  - b\n")
        assert load_config(path).all_usernames == ["a", "b"]

    def test_weights_are_normalised_to_one(self, tmp_path):
        path = self._write(
            tmp_path,
            "competitors:\n  - a\nweights:\n  engagement_rate: 70\n  followers: 30\n",
        )
        weights = load_config(path).weights

        assert sum(weights.values()) == pytest.approx(1.0)
        assert weights["engagement_rate"] == pytest.approx(0.7)

    def test_defaults_applied_when_omitted(self, tmp_path):
        path = self._write(tmp_path, "competitors:\n  - a\n")
        config = load_config(path)

        assert config.posts_limit == 25
        assert config.lookback_days == 30
        assert sum(config.weights.values()) == pytest.approx(1.0)

    def test_json_config_supported(self, tmp_path):
        path = self._write(tmp_path, '{"competitors": ["a", "b"]}', name="c.json")
        assert load_config(path).all_usernames == ["a", "b"]

    def test_missing_file_is_reported(self, tmp_path):
        with pytest.raises(ConfigError, match="tidak ditemukan"):
            load_config(tmp_path / "nope.yml")

    def test_empty_competitor_list_rejected(self, tmp_path):
        path = self._write(tmp_path, "competitors: []\n")
        with pytest.raises(ConfigError, match="tidak boleh kosong"):
            load_config(path)

    def test_unknown_weight_metric_rejected(self, tmp_path):
        path = self._write(tmp_path, "competitors:\n  - a\nweights:\n  vibes: 1.0\n")
        with pytest.raises(ConfigError, match="tidak dikenal"):
            load_config(path)

    def test_out_of_range_posts_limit_rejected(self, tmp_path):
        path = self._write(tmp_path, "competitors:\n  - a\nposts_limit: 500\n")
        with pytest.raises(ConfigError, match="posts_limit"):
            load_config(path)


class TestCsvImport:
    def test_detects_file_kind_from_headers(self):
        assert detect_kind({"username", "followers_count"}) == "snapshots"
        assert detect_kind({"username", "post_id", "like_count"}) == "posts"

    def test_unknown_headers_rejected(self):
        with pytest.raises(ImportError_, match="tidak dikenali"):
            detect_kind({"foo", "bar"})

    def test_imports_snapshots(self, db, tmp_path):
        path = tmp_path / "s.csv"
        path.write_text(
            "username,captured_at,followers_count,media_count\n"
            "@acme,2024-05-01,10000,120\n"
            "rival,2024-05-01,25000,300\n",
            encoding="utf-8",
        )

        kind, count = import_csv(db, path)

        assert (kind, count) == ("snapshots", 2)
        assert storage.latest_snapshot(db, "acme").followers_count == 10000

    def test_imports_posts_with_alias_columns(self, db, tmp_path):
        path = tmp_path / "p.csv"
        path.write_text(
            "username,post_id,date,likes,comments\n" "acme,p1,2024-05-02,500,25\n",
            encoding="utf-8",
        )

        kind, count = import_csv(db, path)
        stored = storage.posts_between(
            db,
            "acme",
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 12, 31, tzinfo=timezone.utc),
        )

        assert (kind, count) == ("posts", 1)
        assert stored[0].like_count == 500
        assert stored[0].comments_count == 25

    def test_rows_without_username_are_skipped(self, db, tmp_path):
        path = tmp_path / "s.csv"
        path.write_text(
            "username,captured_at,followers_count\n,2024-05-01,100\nacme,2024-05-01,200\n",
            encoding="utf-8",
        )

        _, count = import_csv(db, path)
        assert count == 1

    def test_non_numeric_value_reports_line_number(self, db, tmp_path):
        path = tmp_path / "s.csv"
        path.write_text(
            "username,captured_at,followers_count\nacme,2024-05-01,banyak\n",
            encoding="utf-8",
        )

        with pytest.raises(ImportError_, match="baris 2"):
            import_csv(db, path)

    def test_missing_file_reported(self, db, tmp_path):
        with pytest.raises(ImportError_, match="tidak ditemukan"):
            import_csv(db, tmp_path / "absent.csv")


class TestMetricsFromDatabase:
    def test_end_to_end_metric_computation(self, db, tmp_path):
        storage.save_snapshot(db, snap(10_000, days_ago=30))
        storage.save_snapshot(db, snap(12_000, days_ago=0))
        storage.save_posts(
            db,
            [
                Post("acme", "p1", NOW - timedelta(days=3), 500, 50),
                Post("acme", "p2", NOW - timedelta(days=10), 700, 70),
            ],
        )

        config_path = tmp_path / "c.yml"
        config_path.write_text("competitors:\n  - acme\n", encoding="utf-8")
        config = load_config(config_path)

        result = metrics_for_account(db, "acme", config)

        assert result.followers == 12_000
        assert result.posts_analyzed == 2
        assert result.interactions_per_post == pytest.approx(660.0)
        assert result.engagement_rate == pytest.approx(5.5)
        assert result.follower_growth_abs == 2_000
        assert result.follower_growth_pct == pytest.approx(20.0)

    def test_account_without_snapshot_returns_none(self, db, tmp_path):
        config_path = tmp_path / "c.yml"
        config_path.write_text("competitors:\n  - ghost\n", encoding="utf-8")

        assert metrics_for_account(db, "ghost", load_config(config_path)) is None
