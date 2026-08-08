"""Penyajian leaderboard: tabel konsol, CSV, Markdown, dan laporan HTML."""

from __future__ import annotations

import csv
import html
from datetime import datetime, timezone
from pathlib import Path

from .leaderboard import summarise
from .models import RankedAccount

CSV_COLUMNS = [
    "rank",
    "username",
    "label",
    "score",
    "followers",
    "follower_growth_abs",
    "follower_growth_pct",
    "engagement_rate",
    "avg_likes",
    "avg_comments",
    "interactions_per_post",
    "posting_frequency",
    "posts_analyzed",
    "media_count",
    "best_media_type",
    "top_post_permalink",
    "captured_at",
]


def compact_number(value: float | int) -> str:
    """Format angka besar jadi ringkas: 12.4K, 3.1M."""
    number = float(value)
    sign = "-" if number < 0 else ""
    number = abs(number)

    if number >= 1_000_000_000:
        return f"{sign}{number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"{sign}{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{sign}{number / 1_000:.1f}K"
    return f"{sign}{number:.0f}"


def _growth_text(entry: RankedAccount) -> str:
    pct = entry.metrics.follower_growth_pct
    if pct is None:
        return "n/a"
    return f"{pct:+.2f}%"


def _delta_text(entry: RankedAccount) -> str:
    if entry.rank_delta is None:
        return "  ·"
    if entry.rank_delta > 0:
        return f" ▲{entry.rank_delta}"
    if entry.rank_delta < 0:
        return f" ▼{abs(entry.rank_delta)}"
    return "  ="


def render_table(ranked: list[RankedAccount]) -> str:
    """Tabel teks lebar-tetap untuk ditampilkan di terminal."""
    if not ranked:
        return "Belum ada data untuk diperingkat. Jalankan 'iglead fetch' lebih dulu."

    headers = ["#", "", "Akun", "Skor", "Follower", "Growth", "ER%", "Interaksi", "Post/mgg"]
    rows: list[list[str]] = []

    for entry in ranked:
        m = entry.metrics
        name = m.label if m.label != m.username else f"@{m.username}"
        if m.is_own:
            name += " (kita)"
        rows.append(
            [
                str(entry.rank),
                _delta_text(entry),
                name,
                f"{entry.score:.1f}",
                compact_number(m.followers),
                _growth_text(entry),
                f"{m.engagement_rate:.2f}",
                compact_number(m.interactions_per_post),
                f"{m.posting_frequency:.1f}",
            ]
        )

    widths = [
        max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))
    ]
    # Kolom pertama (peringkat) dan kolom teks akun rata kiri; sisanya rata kanan.
    left_aligned = {1, 2}

    def fmt(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            parts.append(cell.ljust(widths[i]) if i in left_aligned or i == 0
                         else cell.rjust(widths[i]))
        return "  ".join(parts).rstrip()

    lines = [fmt(headers), "  ".join("-" * w for w in widths)]
    lines.extend(fmt(r) for r in rows)

    summary = summarise(ranked)
    leader = summary["leader"]
    lines.append("")
    lines.append(
        f"{summary['accounts']} akun · total {compact_number(summary['total_followers'])} "
        f"follower · rata-rata ER {summary['avg_engagement_rate']:.2f}%"
    )
    if leader is not None:
        lines.append(f"Peringkat 1: @{leader.username} (skor {leader.score:.1f})")
    best = summary["best_engagement"]
    if best is not None:
        lines.append(
            f"Engagement tertinggi: @{best.username} ({best.metrics.engagement_rate:.2f}%)"
        )
    fastest = summary["fastest_growing"]
    if fastest is not None:
        lines.append(
            f"Pertumbuhan tercepat: @{fastest.username} "
            f"({fastest.metrics.follower_growth_pct:+.2f}%)"
        )

    return "\n".join(lines)


def _row_values(entry: RankedAccount) -> dict[str, object]:
    m = entry.metrics
    return {
        "rank": entry.rank,
        "username": m.username,
        "label": m.label,
        "score": round(entry.score, 2),
        "followers": m.followers,
        "follower_growth_abs": m.follower_growth_abs if m.follower_growth_abs is not None else "",
        "follower_growth_pct": round(m.follower_growth_pct, 4)
        if m.follower_growth_pct is not None
        else "",
        "engagement_rate": round(m.engagement_rate, 4),
        "avg_likes": round(m.avg_likes, 2),
        "avg_comments": round(m.avg_comments, 2),
        "interactions_per_post": round(m.interactions_per_post, 2),
        "posting_frequency": round(m.posting_frequency, 2),
        "posts_analyzed": m.posts_analyzed,
        "media_count": m.media_count,
        "best_media_type": m.best_media_type,
        "top_post_permalink": m.top_post_permalink,
        "captured_at": m.captured_at.isoformat(),
    }


def write_csv(ranked: list[RankedAccount], path: str | Path) -> Path:
    """Tulis leaderboard ke CSV untuk diolah di spreadsheet."""
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for entry in ranked:
            writer.writerow(_row_values(entry))
    return path


def render_markdown(ranked: list[RankedAccount]) -> str:
    """Tabel Markdown, cocok ditempel ke Notion/Slack/README."""
    if not ranked:
        return "_Belum ada data untuk diperingkat._"

    generated = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    lines = [
        "# Leaderboard Kompetitor Instagram",
        "",
        f"_Dibuat {generated}_",
        "",
        "| # | Akun | Skor | Follower | Growth | ER % | Interaksi/post | Post/minggu |",
        "|--:|------|-----:|---------:|-------:|-----:|---------------:|------------:|",
    ]

    for entry in ranked:
        m = entry.metrics
        name = f"@{m.username}" + (" **(kita)**" if m.is_own else "")
        lines.append(
            f"| {entry.rank} | {name} | {entry.score:.1f} | "
            f"{compact_number(m.followers)} | {_growth_text(entry)} | "
            f"{m.engagement_rate:.2f} | {compact_number(m.interactions_per_post)} | "
            f"{m.posting_frequency:.1f} |"
        )

    summary = summarise(ranked)
    lines.extend(
        [
            "",
            f"**{summary['accounts']} akun** · total "
            f"{compact_number(summary['total_followers'])} follower · rata-rata ER "
            f"{summary['avg_engagement_rate']:.2f}%",
        ]
    )
    return "\n".join(lines)


_HTML_TEMPLATE = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg: #f6f7f9; --card: #ffffff; --text: #16181d; --muted: #6b7280;
    --line: #e5e7eb; --accent: #d62976; --up: #15803d; --down: #b91c1c;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0f1115; --card: #171a21; --text: #e8eaed; --muted: #9aa1ad;
      --line: #262b34; --accent: #f56040; --up: #4ade80; --down: #f87171;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 2.5rem 1.25rem; background: var(--bg); color: var(--text);
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 .35rem; letter-spacing: -.02em; }}
  .sub {{ color: var(--muted); font-size: .875rem; margin-bottom: 1.75rem; }}
  .cards {{
    display: grid; gap: .875rem; margin-bottom: 1.75rem;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  }}
  .card {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 12px; padding: 1rem 1.1rem;
  }}
  .card .k {{
    color: var(--muted); font-size: .7rem; text-transform: uppercase;
    letter-spacing: .06em; margin-bottom: .35rem;
  }}
  .card .v {{ font-size: 1.5rem; font-weight: 650; letter-spacing: -.02em; }}
  .card .m {{ color: var(--muted); font-size: .8rem; margin-top: .15rem; }}
  .tablewrap {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 12px; overflow-x: auto;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
  th, td {{ padding: .7rem .85rem; text-align: right; white-space: nowrap; }}
  th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
  th {{
    color: var(--muted); font-size: .7rem; text-transform: uppercase;
    letter-spacing: .06em; font-weight: 600; border-bottom: 1px solid var(--line);
  }}
  tbody tr {{ border-bottom: 1px solid var(--line); }}
  tbody tr:last-child {{ border-bottom: 0; }}
  .rank {{ font-variant-numeric: tabular-nums; color: var(--muted); }}
  .top .rank {{ color: var(--accent); font-weight: 700; }}
  .own {{ font-weight: 650; }}
  .own td {{ background: color-mix(in srgb, var(--accent) 8%, transparent); }}
  .tag {{
    display: inline-block; margin-left: .4rem; padding: .05rem .4rem;
    border-radius: 999px; background: var(--accent); color: #fff;
    font-size: .65rem; font-weight: 600; vertical-align: 1px;
  }}
  .up {{ color: var(--up); }} .down {{ color: var(--down); }}
  .bar {{
    height: 5px; border-radius: 3px; background: var(--accent);
    display: inline-block; vertical-align: middle; margin-right: .45rem;
  }}
  a {{ color: inherit; }}
  footer {{ color: var(--muted); font-size: .78rem; margin-top: 1.5rem; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{title}</h1>
  <div class="sub">Dibuat {generated} · periode analisis {lookback} hari terakhir</div>
  <div class="cards">{cards}</div>
  <div class="tablewrap">
    <table>
      <thead><tr>
        <th>#</th><th>Akun</th><th>Skor</th><th>Follower</th><th>Growth</th>
        <th>ER %</th><th>Interaksi/post</th><th>Post/mgg</th><th>Analisis</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <footer>
    Skor komposit dinormalisasi terhadap peserta leaderboard: 100 = terbaik di
    antara akun yang dibandingkan. Bobot: {weights}.
  </footer>
</div>
</body>
</html>
"""


def _card(key: str, value: str, meta: str = "") -> str:
    meta_html = f'<div class="m">{html.escape(meta)}</div>' if meta else ""
    return (
        f'<div class="card"><div class="k">{html.escape(key)}</div>'
        f'<div class="v">{html.escape(value)}</div>{meta_html}</div>'
    )


def render_html(
    ranked: list[RankedAccount], config=None, title: str = "Leaderboard Kompetitor Instagram"
) -> str:
    """Laporan HTML mandiri (tanpa aset eksternal), mengikuti tema terang/gelap."""
    generated = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    lookback = getattr(config, "lookback_days", 30)
    weights = getattr(config, "weights", {}) or {}
    weights_text = ", ".join(
        f"{name.replace('_', ' ')} {value * 100:.0f}%"
        for name, value in sorted(weights.items(), key=lambda kv: -kv[1])
    ) or "default"

    if not ranked:
        body_rows = (
            '<tr><td colspan="9" style="text-align:center;padding:2rem">'
            "Belum ada data. Jalankan <code>iglead fetch</code> lebih dulu."
            "</td></tr>"
        )
        cards = _card("Akun terpantau", "0")
        return _HTML_TEMPLATE.format(
            title=html.escape(title),
            generated=generated,
            lookback=lookback,
            cards=cards,
            rows=body_rows,
            weights=html.escape(weights_text),
        )

    summary = summarise(ranked)
    leader = summary["leader"]
    best = summary["best_engagement"]
    fastest = summary["fastest_growing"]

    cards = "".join(
        [
            _card("Akun terpantau", str(summary["accounts"])),
            _card("Total follower", compact_number(summary["total_followers"])),
            _card("Rata-rata ER", f"{summary['avg_engagement_rate']:.2f}%"),
            _card("Peringkat 1", f"@{leader.username}", f"skor {leader.score:.1f}"),
            _card(
                "ER tertinggi",
                f"@{best.username}",
                f"{best.metrics.engagement_rate:.2f}%",
            ),
        ]
        + (
            [
                _card(
                    "Tumbuh tercepat",
                    f"@{fastest.username}",
                    f"{fastest.metrics.follower_growth_pct:+.2f}%",
                )
            ]
            if fastest
            else []
        )
    )

    top_score = max(r.score for r in ranked) or 1.0
    rows: list[str] = []
    for entry in ranked:
        m = entry.metrics
        classes = " ".join(
            filter(None, ["top" if entry.rank == 1 else "", "own" if m.is_own else ""])
        )
        tag = '<span class="tag">kita</span>' if m.is_own else ""
        name = html.escape(m.label if m.label != m.username else f"@{m.username}")
        profile_url = f"https://www.instagram.com/{m.username}/"
        name = (
            f'<a href="{html.escape(profile_url)}" title="Buka profil @{html.escape(m.username)}">'
            f"{name}</a>"
        )

        pct = m.follower_growth_pct
        if pct is None:
            growth = '<span style="opacity:.5">n/a</span>'
        else:
            growth = f'<span class="{"up" if pct >= 0 else "down"}">{pct:+.2f}%</span>'

        delta = ""
        if entry.rank_delta:
            direction = "up" if entry.rank_delta > 0 else "down"
            arrow = "▲" if entry.rank_delta > 0 else "▼"
            delta = f' <span class="{direction}">{arrow}{abs(entry.rank_delta)}</span>'

        analysis_cell = f"{m.posts_analyzed} post"
        if m.top_post_permalink:
            analysis_cell += (
                f' · <a href="{html.escape(m.top_post_permalink)}" '
                f'title="Post dengan interaksi tertinggi">top post</a>'
            )

        bar = int(entry.score / top_score * 46) + 2
        rows.append(
            f'<tr class="{classes}">'
            f'<td class="rank">{entry.rank}{delta}</td>'
            f"<td>{name}{tag}</td>"
            f'<td><span class="bar" style="width:{bar}px"></span>{entry.score:.1f}</td>'
            f"<td>{compact_number(m.followers)}</td>"
            f"<td>{growth}</td>"
            f"<td>{m.engagement_rate:.2f}</td>"
            f"<td>{compact_number(m.interactions_per_post)}</td>"
            f"<td>{m.posting_frequency:.1f}</td>"
            f'<td style="color:var(--muted)">{analysis_cell}</td>'
            "</tr>"
        )

    return _HTML_TEMPLATE.format(
        title=html.escape(title),
        generated=generated,
        lookback=lookback,
        cards=cards,
        rows="".join(rows),
        weights=html.escape(weights_text),
    )


def write_html(
    ranked: list[RankedAccount], path: str | Path, config=None, title: str | None = None
) -> Path:
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {"config": config}
    if title:
        kwargs["title"] = title
    path.write_text(render_html(ranked, **kwargs), encoding="utf-8")
    return path
