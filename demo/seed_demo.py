"""Isi database demo dengan data sintetis agar tool bisa dicoba tanpa token API.

Jalankan:
    python demo/seed_demo.py
    iglead --config demo/competitors.demo.yml --db demo.db rank --compare-days 14
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iglead import storage  # noqa: E402
from iglead.models import Post, Snapshot  # noqa: E402

DB_PATH = "demo.db"
DAYS = 60

# username, follower awal, pertumbuhan harian %, engagement dasar %, post/minggu
PROFILES = [
    ("kopisenja",      48_000, 0.0075, 0.052, 5),
    ("rotibakarmalam", 132_000, 0.0021, 0.019, 3),
    ("dapurumami",      96_500, 0.0044, 0.031, 4),
    ("brand_saya",      61_200, 0.0033, 0.036, 4),
    ("nusantarabites", 210_000, 0.0009, 0.011, 2),
]

MEDIA_TYPES = ["IMAGE", "CAROUSEL_ALBUM", "VIDEO", "VIDEO", "IMAGE"]


def seed(db_path: str = DB_PATH, seed_value: int = 20240501) -> None:
    rng = random.Random(seed_value)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=DAYS)

    with storage.connect(db_path) as conn:
        for username, base_followers, daily_growth, base_er, per_week in PROFILES:
            followers = float(base_followers)
            media_count = rng.randint(300, 1400)

            # Snapshot harian: pertumbuhan tren + guncangan acak kecil.
            for day in range(DAYS + 1):
                captured_at = start + timedelta(days=day)
                noise = rng.uniform(-0.0012, 0.0012)
                followers *= 1 + daily_growth + noise
                storage.save_snapshot(
                    conn,
                    Snapshot(
                        username=username,
                        captured_at=captured_at,
                        followers_count=int(followers),
                        media_count=media_count + day * per_week // 7,
                        biography=f"Akun demo @{username}",
                    ),
                )

            # Post tersebar di sepanjang periode, dengan interaksi proporsional
            # terhadap jumlah follower saat itu.
            total_posts = int(per_week * DAYS / 7)
            for index in range(total_posts):
                offset_days = DAYS * index / max(total_posts, 1)
                timestamp = start + timedelta(days=offset_days, hours=rng.randint(6, 21))
                followers_then = base_followers * (1 + daily_growth) ** offset_days
                engagement = base_er * rng.uniform(0.55, 1.75)
                interactions = followers_then * engagement
                comments = int(interactions * rng.uniform(0.03, 0.09))

                storage.save_posts(
                    conn,
                    [
                        Post(
                            username=username,
                            post_id=f"demo_{username}_{index}",
                            timestamp=timestamp,
                            like_count=max(0, int(interactions) - comments),
                            comments_count=comments,
                            media_type=rng.choice(MEDIA_TYPES),
                            permalink=f"https://instagram.com/p/demo{username[:4]}{index}/",
                            caption=f"Post demo #{index} dari @{username}",
                        )
                    ],
                )

        counts = storage.stats(conn)

    print(f"Data demo dibuat di {db_path}")
    print(f"  {counts['accounts']} akun · {counts['snapshots']} snapshot · {counts['posts']} post")
    print("\nCoba jalankan:")
    print("  python -m iglead --config demo/competitors.demo.yml --db demo.db rank --compare-days 14")
    print("  python -m iglead --config demo/competitors.demo.yml --db demo.db report -o demo_report.html")


if __name__ == "__main__":
    seed()
