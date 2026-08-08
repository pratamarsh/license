"""Klien Instagram Graph API (endpoint business_discovery).

Data kompetitor diambil lewat `business_discovery`, jalur resmi Meta untuk
membaca metrik publik akun Business/Creator lain. Konsekuensinya:

* Akun pemanggil harus Instagram Business/Creator yang tertaut ke Facebook Page.
* Akun target juga harus Business/Creator. Akun personal/privat tidak terbaca
  dan akan menghasilkan error yang kami tandai sebagai `AccountNotDiscoverable`.
* Token butuh scope: instagram_basic, instagram_manage_insights,
  pages_read_engagement, pages_show_list.

Tidak ada scraping di sini; semuanya lewat API resmi.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .models import Post, Snapshot

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Kode error Graph API yang layak dicoba ulang (rate limit / gangguan sementara).
RETRYABLE_CODES = {1, 2, 4, 17, 32, 341, 613}


class InstagramError(Exception):
    """Kegagalan umum saat memanggil Graph API."""


class AuthError(InstagramError):
    """Token tidak valid, kedaluwarsa, atau kurang scope."""


class AccountNotDiscoverable(InstagramError):
    """Akun target tidak bisa dibaca via business_discovery."""


class RateLimited(InstagramError):
    """Kuota API habis setelah seluruh percobaan ulang."""


def _parse_ig_timestamp(value: str) -> datetime:
    """Parse timestamp Graph API (mis. '2024-05-01T10:30:00+0000') ke UTC."""
    try:
        # Python <3.11 tidak menerima offset tanpa titik dua; normalkan dulu.
        if len(value) >= 5 and value[-5] in "+-" and ":" not in value[-5:]:
            value = value[:-2] + ":" + value[-2:]
        dt = datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class InstagramClient:
    """Pembungkus tipis Graph API dengan retry dan pesan error yang jelas."""

    def __init__(
        self,
        access_token: str,
        business_account_id: str,
        *,
        timeout: int = 30,
        max_retries: int = 4,
        sleep=time.sleep,
    ) -> None:
        self.access_token = access_token
        self.business_account_id = business_account_id
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep

    # ------------------------------------------------------------------ HTTP

    def _request(self, path: str, params: dict[str, str]) -> dict:
        query = dict(params, access_token=self.access_token)
        url = f"{GRAPH_BASE_URL}/{path}?{urllib.parse.urlencode(query)}"

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                error = self._classify(exc.code, body)
                if not isinstance(error, RateLimited) or attempt == self.max_retries - 1:
                    raise error
                last_error = error
            except urllib.error.URLError as exc:
                last_error = InstagramError(f"gangguan jaringan: {exc.reason}")
                if attempt == self.max_retries - 1:
                    raise last_error from exc
            except json.JSONDecodeError as exc:
                raise InstagramError("respons Graph API bukan JSON yang valid") from exc

            self._sleep(2**attempt)  # backoff 1s, 2s, 4s, 8s

        raise last_error or InstagramError("permintaan gagal tanpa keterangan")

    @staticmethod
    def _classify(status: int, body: str) -> InstagramError:
        """Ubah error HTTP Graph API menjadi exception yang spesifik."""
        try:
            payload = json.loads(body).get("error", {})
        except json.JSONDecodeError:
            payload = {}

        message = payload.get("message", body[:300] or f"HTTP {status}")
        code = payload.get("code")
        subcode = payload.get("error_subcode")

        if status in (401, 403) or code in (190, 102):
            return AuthError(
                f"autentikasi ditolak: {message}\n"
                "Periksa masa berlaku token dan scope "
                "(instagram_basic, instagram_manage_insights, pages_read_engagement)."
            )
        if code in RETRYABLE_CODES or status == 429:
            return RateLimited(f"kuota API terlampaui: {message}")
        if code == 100 and subcode == 2207013:
            return AccountNotDiscoverable(message)
        if code == 100:
            # business_discovery mengembalikan code 100 juga untuk username
            # yang tidak ada atau bukan akun Business.
            return AccountNotDiscoverable(
                f"{message} (akun tidak ada, privat, atau bukan Business/Creator)"
            )
        return InstagramError(f"Graph API error (HTTP {status}): {message}")

    # ----------------------------------------------------------------- Publik

    def verify_token(self) -> dict:
        """Cek token & ID akun sendiri; dipakai perintah `iglead check`."""
        return self._request(
            self.business_account_id,
            {"fields": "id,username,followers_count,media_count"},
        )

    def fetch_account(
        self, username: str, posts_limit: int = 25
    ) -> tuple[Snapshot, list[Post]]:
        """Tarik profil dan post terakhir satu akun kompetitor."""
        posts_limit = max(1, min(int(posts_limit), 50))
        fields = (
            f"business_discovery.username({username})"
            "{followers_count,media_count,biography,profile_picture_url,"
            f"media.limit({posts_limit})"
            "{id,timestamp,like_count,comments_count,media_type,permalink,caption}}"
        )

        payload = self._request(self.business_account_id, {"fields": fields})
        discovery = payload.get("business_discovery")
        if not discovery:
            raise AccountNotDiscoverable(
                f"@{username}: Graph API tidak mengembalikan data business_discovery"
            )

        captured_at = datetime.now(timezone.utc)
        snapshot = Snapshot(
            username=username,
            captured_at=captured_at,
            followers_count=int(discovery.get("followers_count") or 0),
            media_count=int(discovery.get("media_count") or 0),
            biography=discovery.get("biography") or "",
            profile_picture_url=discovery.get("profile_picture_url") or "",
        )

        posts: list[Post] = []
        for item in (discovery.get("media") or {}).get("data", []):
            post_id = item.get("id")
            if not post_id:
                continue
            posts.append(
                Post(
                    username=username,
                    post_id=str(post_id),
                    timestamp=_parse_ig_timestamp(item.get("timestamp", "")),
                    # Akun yang menyembunyikan jumlah like mengirim field kosong.
                    like_count=int(item.get("like_count") or 0),
                    comments_count=int(item.get("comments_count") or 0),
                    media_type=item.get("media_type") or "",
                    permalink=item.get("permalink") or "",
                    caption=item.get("caption") or "",
                )
            )

        return snapshot, posts
