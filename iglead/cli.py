"""Antarmuka baris perintah iglead."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__, report, storage
from .config import (
    Config,
    ConfigError,
    load_access_token,
    load_business_account_id,
    load_config,
)
from .csv_io import ImportError_, import_csv
from .instagram import (
    AccountNotDiscoverable,
    InstagramClient,
    InstagramError,
    RateLimited,
)
from .leaderboard import build_leaderboard
from .metrics import metrics_for_account

DEFAULT_CONFIG = "competitors.yml"


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def _load(args) -> Config:
    return load_config(args.config)


# ---------------------------------------------------------------- perintah


def cmd_init(args) -> int:
    """Buat database kosong dan contoh file konfigurasi."""
    with storage.connect(args.db) as conn:
        storage.stats(conn)
    print(f"Database siap: {args.db}")

    config_path = Path(args.config)
    if config_path.exists():
        print(f"Konfigurasi sudah ada: {config_path}")
        return 0

    config_path.write_text(
        "# Akun Instagram Business milik sendiri (opsional, ikut diperingkat).\n"
        "own_account: brand_saya\n"
        "\n"
        "# Daftar kompetitor. Harus akun Business/Creator agar terbaca API.\n"
        "competitors:\n"
        "  - username: kompetitor_a\n"
        '    label: "Kompetitor A"\n'
        "  - username: kompetitor_b\n"
        "  - brand_saya\n"
        "\n"
        "posts_limit: 25        # jumlah post terakhir yang ditarik per akun\n"
        "lookback_days: 30      # rentang analisis engagement & frekuensi\n"
        "growth_window_days: 30 # rentang pembanding pertumbuhan follower\n"
        "\n"
        "# Bobot skor komposit; otomatis dinormalisasi ke total 1.0.\n"
        "weights:\n"
        "  engagement_rate: 0.35\n"
        "  follower_growth_pct: 0.25\n"
        "  followers: 0.15\n"
        "  interactions_per_post: 0.15\n"
        "  posting_frequency: 0.10\n",
        encoding="utf-8",
    )
    print(f"Konfigurasi contoh dibuat: {config_path}")
    print("Sunting file itu, lalu jalankan: iglead fetch")
    return 0


def cmd_check(args) -> int:
    """Verifikasi token dan akses Graph API."""
    config = _load(args)
    token = load_access_token(args.token)
    account_id = load_business_account_id(args.account_id)
    client = InstagramClient(token, account_id)

    try:
        me = client.verify_token()
    except InstagramError as exc:
        _eprint(f"Gagal: {exc}")
        return 1

    print(f"Token valid. Akun pemanggil: @{me.get('username', '?')} (id {me.get('id')})")
    print(f"Follower: {me.get('followers_count', 'n/a')} · Media: {me.get('media_count', 'n/a')}")
    print(f"Kompetitor terdaftar: {len(config.competitors)}")
    return 0


def cmd_fetch(args) -> int:
    """Tarik data terbaru semua akun dan simpan sebagai snapshot."""
    config = _load(args)
    token = load_access_token(args.token)
    account_id = load_business_account_id(args.account_id)
    client = InstagramClient(token, account_id)

    ok, failed = 0, 0
    with storage.connect(args.db) as conn:
        for competitor in config.competitors:
            username = competitor.username
            try:
                snapshot, posts = client.fetch_account(username, config.posts_limit)
            except AccountNotDiscoverable as exc:
                _eprint(f"  ! @{username}: dilewati — {exc}")
                failed += 1
                continue
            except RateLimited as exc:
                _eprint(f"  ! kuota API habis: {exc}")
                _eprint("    Data yang sudah terkumpul tetap tersimpan. Coba lagi nanti.")
                failed += 1
                break
            except InstagramError as exc:
                _eprint(f"  ! @{username}: {exc}")
                failed += 1
                continue

            storage.save_snapshot(conn, snapshot)
            storage.save_posts(conn, posts)
            ok += 1
            print(
                f"  ✓ @{username}: {snapshot.followers_count:,} follower, "
                f"{len(posts)} post tersimpan"
            )

    print(f"\nSelesai: {ok} akun berhasil, {failed} gagal.")
    if ok:
        print("Lihat hasilnya dengan: iglead rank")
    return 0 if failed == 0 else 1


def cmd_import(args) -> int:
    """Impor snapshot atau post dari file CSV."""
    with storage.connect(args.db) as conn:
        try:
            kind, count = import_csv(conn, args.path, args.kind)
        except ImportError_ as exc:
            _eprint(f"Gagal impor: {exc}")
            return 1
    print(f"{count} baris {kind} diimpor dari {args.path}")
    return 0


def cmd_rank(args) -> int:
    """Tampilkan leaderboard di terminal."""
    config = _load(args)
    compare_as_of = (
        datetime.now(timezone.utc) - timedelta(days=args.compare_days)
        if args.compare_days
        else None
    )

    with storage.connect(args.db) as conn:
        ranked, missing = build_leaderboard(conn, config, compare_as_of=compare_as_of)

    print(report.render_markdown(ranked) if args.markdown else report.render_table(ranked))

    if missing:
        _eprint(
            "\nBelum ada data untuk: "
            + ", ".join(f"@{u}" for u in missing)
            + "\nJalankan 'iglead fetch' atau impor CSV untuk akun tersebut."
        )
    if args.csv:
        path = report.write_csv(ranked, args.csv)
        print(f"\nCSV ditulis ke {path}")
    return 0


def cmd_report(args) -> int:
    """Hasilkan laporan HTML mandiri."""
    config = _load(args)
    compare_as_of = (
        datetime.now(timezone.utc) - timedelta(days=args.compare_days)
        if args.compare_days
        else None
    )

    with storage.connect(args.db) as conn:
        ranked, missing = build_leaderboard(conn, config, compare_as_of=compare_as_of)

    path = report.write_html(ranked, args.output, config=config, title=args.title)
    print(f"Laporan HTML ditulis ke {path}")
    if missing:
        _eprint("Belum ada data untuk: " + ", ".join(f"@{u}" for u in missing))
    return 0


def cmd_history(args) -> int:
    """Tampilkan riwayat follower satu akun."""
    config = _load(args)
    username = args.username.lstrip("@")

    with storage.connect(args.db) as conn:
        history = storage.snapshot_history(conn, username)
        current = metrics_for_account(conn, username, config)

    if not history:
        _eprint(f"Belum ada snapshot untuk @{username}")
        return 1

    print(f"Riwayat @{username} ({len(history)} snapshot)\n")
    print(f"{'Tanggal':<12} {'Follower':>12} {'Δ':>10} {'Post':>7}")
    print("-" * 43)

    previous: int | None = None
    for snapshot in history:
        delta = "—" if previous is None else f"{snapshot.followers_count - previous:+,}"
        print(
            f"{snapshot.captured_at.strftime('%Y-%m-%d'):<12} "
            f"{snapshot.followers_count:>12,} {delta:>10} "
            f"{snapshot.media_count:>7,}"
        )
        previous = snapshot.followers_count

    if current:
        print()
        print(f"Engagement rate  : {current.engagement_rate:.2f}%")
        print(f"Interaksi/post   : {current.interactions_per_post:,.0f}")
        print(f"Frekuensi posting: {current.posting_frequency:.1f} post/minggu")
        if current.follower_growth_pct is not None:
            print(
                f"Pertumbuhan      : {current.follower_growth_abs:+,} "
                f"({current.follower_growth_pct:+.2f}%)"
            )
    return 0


def cmd_status(args) -> int:
    """Ringkasan isi database."""
    with storage.connect(args.db) as conn:
        counts = storage.stats(conn)
        usernames = storage.tracked_usernames(conn)

    print(f"Database : {args.db}")
    print(f"Akun     : {counts['accounts']}")
    print(f"Snapshot : {counts['snapshots']}")
    print(f"Post     : {counts['posts']}")
    if usernames:
        print("\nTerpantau: " + ", ".join(f"@{u}" for u in usernames))
    return 0


# ------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iglead",
        description="Leaderboard kompetitor Instagram berbasis Graph API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Contoh:\n"
            "  iglead init                       # siapkan config + database\n"
            "  iglead check                      # uji token Graph API\n"
            "  iglead fetch                      # tarik data kompetitor\n"
            "  iglead rank --compare-days 7      # leaderboard + pergerakan\n"
            "  iglead report -o leaderboard.html # laporan HTML\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"iglead {__version__}")
    parser.add_argument(
        "-c", "--config", default=DEFAULT_CONFIG, help=f"file konfigurasi (default: {DEFAULT_CONFIG})"
    )
    parser.add_argument(
        "--db", default=storage.DEFAULT_DB_PATH, help="lokasi database SQLite"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="buat database dan konfigurasi contoh")
    p.set_defaults(func=cmd_init)

    for name, help_text, func in (
        ("check", "verifikasi token dan akses Graph API", cmd_check),
        ("fetch", "tarik data terbaru dari Instagram", cmd_fetch),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--token", help="access token (default: env IG_ACCESS_TOKEN)")
        p.add_argument(
            "--account-id", help="IG Business Account ID (default: env IG_BUSINESS_ACCOUNT_ID)"
        )
        p.set_defaults(func=func)

    p = sub.add_parser("import", help="impor snapshot/post dari CSV")
    p.add_argument("path", help="file CSV yang akan diimpor")
    p.add_argument(
        "--kind", choices=["snapshots", "posts"], help="paksa jenis file (default: deteksi otomatis)"
    )
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("rank", help="tampilkan leaderboard")
    p.add_argument("--csv", help="tulis juga ke file CSV")
    p.add_argument("--markdown", action="store_true", help="keluarkan tabel Markdown")
    p.add_argument(
        "--compare-days",
        type=int,
        metavar="N",
        help="bandingkan dengan peringkat N hari lalu",
    )
    p.set_defaults(func=cmd_rank)

    p = sub.add_parser("report", help="hasilkan laporan HTML")
    p.add_argument("-o", "--output", default="leaderboard.html", help="file keluaran")
    p.add_argument("--title", help="judul laporan")
    p.add_argument(
        "--compare-days", type=int, metavar="N", help="bandingkan dengan peringkat N hari lalu"
    )
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("history", help="riwayat follower satu akun")
    p.add_argument("username", help="username kompetitor")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("status", help="ringkasan isi database")
    p.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        _eprint(f"Konfigurasi bermasalah: {exc}")
        return 2
    except KeyboardInterrupt:
        _eprint("\nDibatalkan.")
        return 130
    except BrokenPipeError:
        # Terjadi saat keluaran dipipe ke 'head' dan pembacanya berhenti duluan.
        try:
            sys.stdout.close()
        finally:
            return 0


if __name__ == "__main__":
    sys.exit(main())
