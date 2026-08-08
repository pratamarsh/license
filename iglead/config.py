"""Pembacaan dan validasi file konfigurasi."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Bobot default untuk skor komposit. Totalnya harus 1.0.
DEFAULT_WEIGHTS: dict[str, float] = {
    "engagement_rate": 0.35,
    "follower_growth_pct": 0.25,
    "followers": 0.15,
    "interactions_per_post": 0.15,
    "posting_frequency": 0.10,
}

# Metrik yang boleh dipakai sebagai komponen skor.
SCORABLE_METRICS = frozenset(DEFAULT_WEIGHTS)


class ConfigError(Exception):
    """Konfigurasi tidak valid atau tidak bisa dibaca."""


@dataclass(frozen=True)
class Competitor:
    username: str
    label: str

    @property
    def display(self) -> str:
        return self.label or self.username


@dataclass
class Config:
    #: Akun bisnis milik sendiri; dipakai sebagai identitas pemanggil Graph API
    #: sekaligus ikut diperingkat sebagai pembanding.
    own_account: str
    competitors: list[Competitor] = field(default_factory=list)
    #: Jumlah post terakhir yang ditarik per akun (batas Graph API: 50).
    posts_limit: int = 25
    #: Rentang hari yang dipakai saat menghitung engagement & frekuensi posting.
    lookback_days: int = 30
    #: Rentang hari untuk membandingkan pertumbuhan follower.
    growth_window_days: int = 30
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    @property
    def all_usernames(self) -> list[str]:
        return [c.username for c in self.competitors]

    def label_for(self, username: str) -> str:
        for c in self.competitors:
            if c.username == username:
                return c.display
        return username


def _normalise_username(raw: str) -> str:
    """Terima '@nama', URL profil, atau nama polos -> kembalikan nama polos."""
    name = str(raw).strip()
    if not name:
        raise ConfigError("username kompetitor tidak boleh kosong")
    if "instagram.com" in name:
        name = name.rstrip("/").rsplit("/", 1)[-1]
    return name.lstrip("@").strip()


def _parse_competitors(raw: object) -> list[Competitor]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError("'competitors' harus berupa list dan tidak boleh kosong")

    seen: set[str] = set()
    out: list[Competitor] = []
    for entry in raw:
        if isinstance(entry, str):
            username, label = _normalise_username(entry), ""
        elif isinstance(entry, dict):
            if "username" not in entry:
                raise ConfigError(f"entri kompetitor tanpa 'username': {entry!r}")
            username = _normalise_username(entry["username"])
            label = str(entry.get("label", "") or "")
        else:
            raise ConfigError(f"entri kompetitor harus string atau mapping: {entry!r}")

        key = username.lower()
        if key in seen:
            continue  # duplikat diabaikan diam-diam agar config bisa di-copy-paste
        seen.add(key)
        out.append(Competitor(username=username, label=label))
    return out


def _parse_weights(raw: object) -> dict[str, float]:
    if raw is None:
        return dict(DEFAULT_WEIGHTS)
    if not isinstance(raw, dict):
        raise ConfigError("'weights' harus berupa mapping metrik -> angka")

    unknown = set(raw) - SCORABLE_METRICS
    if unknown:
        raise ConfigError(
            "metrik tidak dikenal di 'weights': "
            + ", ".join(sorted(unknown))
            + ". Pilihan: "
            + ", ".join(sorted(SCORABLE_METRICS))
        )

    weights: dict[str, float] = {}
    for name, value in raw.items():
        try:
            weight = float(value)
        except (TypeError, ValueError):
            raise ConfigError(f"bobot '{name}' bukan angka: {value!r}") from None
        if weight < 0:
            raise ConfigError(f"bobot '{name}' tidak boleh negatif")
        weights[name] = weight

    total = sum(weights.values())
    if total <= 0:
        raise ConfigError("total bobot harus lebih besar dari nol")
    # Dinormalisasi supaya skor akhir selalu berada di skala 0-100 walaupun
    # pengguna menulis bobot sebagai 35/25/15/15/10.
    return {name: weight / total for name, weight in weights.items()}


def _parse_int(data: dict, key: str, default: int, minimum: int, maximum: int) -> int:
    if key not in data or data[key] is None:
        return default
    try:
        value = int(data[key])
    except (TypeError, ValueError):
        raise ConfigError(f"'{key}' harus berupa bilangan bulat") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"'{key}' harus di antara {minimum} dan {maximum}")
    return value


def load_config(path: str | Path) -> Config:
    """Baca konfigurasi dari file YAML atau JSON."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"file konfigurasi tidak ditemukan: {path}\n"
            "Salin competitors.example.yml lalu sesuaikan."
        )

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yml", ".yaml"}:
        try:
            import yaml
        except ImportError:
            raise ConfigError(
                "PyYAML belum terpasang. Jalankan 'pip install pyyaml' "
                "atau pakai konfigurasi berformat .json."
            ) from None
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"YAML tidak valid di {path}: {exc}") from exc
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"JSON tidak valid di {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"konfigurasi di {path} harus berupa mapping")

    own_raw = data.get("own_account") or ""
    own_account = _normalise_username(own_raw) if own_raw else ""

    return Config(
        own_account=own_account,
        competitors=_parse_competitors(data.get("competitors")),
        posts_limit=_parse_int(data, "posts_limit", 25, 1, 50),
        lookback_days=_parse_int(data, "lookback_days", 30, 1, 365),
        growth_window_days=_parse_int(data, "growth_window_days", 30, 1, 365),
        weights=_parse_weights(data.get("weights")),
    )


def load_access_token(explicit: str | None = None) -> str:
    """Ambil access token dari argumen CLI, lalu .env, lalu environment."""
    if explicit:
        return explicit.strip()

    for key in ("IG_ACCESS_TOKEN", "INSTAGRAM_ACCESS_TOKEN"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()

    dotenv = Path(".env")
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() in {"IG_ACCESS_TOKEN", "INSTAGRAM_ACCESS_TOKEN"}:
                return value.strip().strip("'\"")

    raise ConfigError(
        "access token tidak ditemukan. Set IG_ACCESS_TOKEN di environment "
        "atau file .env, atau pakai flag --token."
    )


def load_business_account_id(explicit: str | None = None) -> str:
    """Ambil IG Business Account ID (ID numerik akun sendiri)."""
    if explicit:
        return explicit.strip()

    value = os.environ.get("IG_BUSINESS_ACCOUNT_ID")
    if value and value.strip():
        return value.strip()

    dotenv = Path(".env")
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("IG_BUSINESS_ACCOUNT_ID=") and "=" in line:
                return line.partition("=")[2].strip().strip("'\"")

    raise ConfigError(
        "IG_BUSINESS_ACCOUNT_ID tidak ditemukan. Ini ID numerik akun Instagram "
        "Business milik Anda sendiri (bukan username). Lihat README bagian Setup."
    )
