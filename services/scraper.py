from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


SCHOOL_URL = "https://spmb.jabarprov.go.id/sekolah/025d2e40-bed3-4c44-a1ec-af4dcec70890"
RANKING_BY_NISN_URL = "https://spmb.jabarprov.go.id/ranking-sementara"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Participant:
    name: str
    rank: int
    score: Optional[float]


class FetchStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    ERROR = "ERROR"


@dataclass(frozen=True)
class FetchResult:
    status: FetchStatus
    participant: Optional[Participant]
    error: Optional[str] = None


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _parse_ranking_by_nisn_html(html: str) -> Optional[Participant]:
    name_match = re.search(r">Nama</p><p[^>]*>([^<]+)</p>", html)
    rank_match = re.search(r">Posisi Anda</p>.*?>#(\d{1,5})<", html, flags=re.DOTALL)
    score_match = re.search(r">Skor Akhir</p><p[^>]*>([0-9.,]+)</p>", html)

    if not name_match or not rank_match:
        return None

    name = name_match.group(1).strip()
    try:
        rank = int(rank_match.group(1))
    except ValueError:
        return None

    score = None
    if score_match:
        score = _try_parse_float(score_match.group(1))

    return Participant(name=name, rank=rank, score=score)


def _get_spmb_cookie_header() -> Optional[str]:
    raw = (os.getenv("SPMB_COOKIE") or "").strip()
    return raw or None


def fetch_participant_by_nisn(
    target_nisn: str,
    *,
    timeout_seconds: int = 20,
    url: str = RANKING_BY_NISN_URL,
) -> FetchResult:
    nisn = (target_nisn or "").strip()
    if not nisn:
        return FetchResult(status=FetchStatus.NOT_FOUND, participant=None)

    base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    session = requests.Session()
    cookie_header = _get_spmb_cookie_header()
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            **({"Cookie": cookie_header} if cookie_header else {}),
        }
    )

    def warmup() -> None:
        try:
            session.get(
                base_url + "/",
                timeout=(10, timeout_seconds),
                headers={
                    "Referer": base_url + "/",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
        except requests.RequestException:
            return

    last_error: Optional[str] = None
    for attempt in range(1, 4):
        try:
            warmup()
            resp = session.get(
                url,
                params={"nisn": nisn},
                timeout=(10, timeout_seconds),
                allow_redirects=True,
                headers={
                    "Referer": base_url + "/",
                    "Origin": base_url,
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
            status = resp.status_code
            html = resp.text or ""

            if status != 200:
                last_error = f"HTTP {status}"
                logger.warning("Gagal ambil ranking (NISN) | status=%s | attempt=%s", status, attempt)
                time.sleep(min(2 * attempt, 5))
                continue

            lowered = html.lower()
            if any(
                token in lowered
                for token in (
                    "just a moment",
                    "attention required",
                    "cf-chl",
                    "cloudflare",
                    "im_under_attack_box",
                    "ray id",
                )
            ):
                last_error = "Terblokir oleh proteksi (Cloudflare)"
                logger.warning("Terblokir proteksi saat ambil ranking (NISN) | attempt=%s", attempt)
                time.sleep(min(2 * attempt, 5))
                continue

            participant = _parse_ranking_by_nisn_html(html)
            if participant is None:
                return FetchResult(status=FetchStatus.NOT_FOUND, participant=None)

            return FetchResult(status=FetchStatus.FOUND, participant=participant)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_error = f"{type(e).__name__}"
            logger.warning("Timeout/koneksi saat ambil ranking (NISN) | error=%s | attempt=%s", type(e).__name__, attempt)
            time.sleep(min(2 * attempt, 5))
            continue
        except requests.RequestException as e:
            last_error = f"{type(e).__name__}"
            logger.warning("Request error saat ambil ranking (NISN) | error=%s | attempt=%s", type(e).__name__, attempt)
            time.sleep(min(2 * attempt, 5))
            continue

    return FetchResult(
        status=FetchStatus.ERROR,
        participant=None,
        error=(
            "Website tidak dapat diakses (HTTP 403). "
            "Jika halaman bisa dibuka di browser tapi gagal via script, set env SPMB_COOKIE dari browser."
            if last_error == "HTTP 403"
            else f"Website tidak dapat diakses ({last_error or 'unknown'})"
        ),
    )


def _try_parse_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        s = re.sub(r"[^\d-]", "", s)
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _try_parse_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", ".")
        s = re.sub(r"[^0-9.\-]", "", s)
        if not s or s in {".", "-", "-."}:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _walk_json(obj: Any) -> Iterable[Any]:
    stack = [obj]
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _extract_participants_from_json(obj: Any) -> list[Participant]:
    participants: list[Participant] = []
    for node in _walk_json(obj):
        if not isinstance(node, list) or not node:
            continue
        if not all(isinstance(item, dict) for item in node):
            continue

        for item in node:
            name = None
            for key in ("nama", "name", "nama_peserta", "namaPeserta"):
                if key in item and isinstance(item[key], str) and item[key].strip():
                    name = item[key].strip()
                    break

            if not name:
                continue

            rank = None
            for key in ("peringkat", "rank", "ranking", "urutan", "posisi"):
                if key in item:
                    rank = _try_parse_int(item[key])
                    if rank is not None:
                        break

            if rank is None:
                continue

            score = None
            for key in ("nilai", "score", "skor", "nilai_total", "nilaiTotal"):
                if key in item:
                    score = _try_parse_float(item[key])
                    if score is not None:
                        break

            participants.append(Participant(name=name, rank=rank, score=score))
    return participants


def _candidate_api_urls_from_text(text: str, base_url: str) -> list[str]:
    urls: set[str] = set()

    for absolute in re.findall(r"https?://[^\s\"']+", text, flags=re.IGNORECASE):
        if "/api" in absolute or "graphql" in absolute.lower():
            urls.add(absolute.rstrip(");,"))

    for relative in re.findall(r"(?<![a-zA-Z0-9_])/(?:api|graphql)[^\s\"']*", text):
        urls.add(urljoin(base_url, relative.rstrip(");,")))

    return sorted(urls)


def _same_host(url: str, base: str) -> bool:
    try:
        return urlparse(url).netloc == urlparse(base).netloc
    except Exception:
        return False


def _fetch_json(session: requests.Session, url: str, timeout: int) -> Optional[Any]:
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type.lower():
            return resp.json()
        try:
            return resp.json()
        except json.JSONDecodeError:
            return None
    except requests.RequestException:
        return None


def _find_by_name(participants: list[Participant], target_name: str) -> Optional[Participant]:
    target_norm = _normalize_name(target_name)
    if not target_norm:
        return None

    for p in participants:
        if _normalize_name(p.name) == target_norm:
            return p

    for p in participants:
        if target_norm in _normalize_name(p.name):
            return p

    return None


def _html_fallback_find_participant(html: str, target_name: str) -> Optional[Participant]:
    soup = BeautifulSoup(html, "html.parser")
    target_norm = _normalize_name(target_name)
    if not target_norm:
        return None

    for tr in soup.find_all("tr"):
        row_text = _normalize_name(tr.get_text(" ", strip=True))
        if not row_text:
            continue
        if target_norm not in row_text:
            continue

        tds = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        rank = None
        score = None

        for cell in tds:
            if rank is None:
                rank = _try_parse_int(cell)
            if score is None:
                score = _try_parse_float(cell)
        if rank is None:
            continue

        name_guess = target_name
        for cell in tds:
            if _normalize_name(cell) == target_norm:
                name_guess = cell.strip()
                break

        return Participant(name=name_guess, rank=rank, score=score)

    return None


def fetch_participant(
    target_name: str,
    *,
    url: str = SCHOOL_URL,
    timeout_seconds: int = 20,
) -> FetchResult:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )

    try:
        resp = session.get(url, timeout=timeout_seconds)
        resp.raise_for_status()
        html = resp.text
    except requests.RequestException:
        return FetchResult(status=FetchStatus.ERROR, participant=None, error="Website tidak dapat diakses")

    base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    school_id = urlparse(url).path.rstrip("/").split("/")[-1]

    candidates: list[str] = []
    candidates.extend(_candidate_api_urls_from_text(html, base_url))

    soup = BeautifulSoup(html, "html.parser")
    script_srcs = []
    for s in soup.find_all("script"):
        src = s.get("src")
        if not src:
            continue
        full = urljoin(base_url, src)
        if _same_host(full, base_url):
            script_srcs.append(full)
    for js_url in script_srcs[:10]:
        try:
            js_resp = session.get(js_url, timeout=timeout_seconds)
            if js_resp.status_code == 200 and js_resp.text:
                candidates.extend(_candidate_api_urls_from_text(js_resp.text, base_url))
        except requests.RequestException:
            continue

    guess_paths = [
        "/api",
        "/api/",
        "/api/v1",
        "/api/v1/",
        "/api/v2",
        "/api/v2/",
        "/graphql",
    ]
    for gp in guess_paths:
        candidates.append(urljoin(base_url, gp))

    if school_id:
        school_guesses = [
            f"/api/sekolah/{school_id}",
            f"/api/sekolah/{school_id}/ranking",
            f"/api/sekolah/{school_id}/peringkat",
            f"/api/sekolah/{school_id}/pendaftar",
            f"/api/v1/sekolah/{school_id}",
            f"/api/v1/sekolah/{school_id}/ranking",
            f"/api/v1/sekolah/{school_id}/peringkat",
            f"/api/v1/sekolah/{school_id}/pendaftar",
            f"/api/v2/sekolah/{school_id}",
            f"/api/v2/sekolah/{school_id}/ranking",
            f"/api/v2/sekolah/{school_id}/peringkat",
            f"/api/v2/sekolah/{school_id}/pendaftar",
        ]
        for sg in school_guesses:
            candidates.append(urljoin(base_url, sg))

    deduped: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        deduped.append(c)

    for api_url in deduped:
        data = _fetch_json(session, api_url, timeout=timeout_seconds)
        if data is None:
            continue
        participants = _extract_participants_from_json(data)
        found = _find_by_name(participants, target_name)
        if found is not None:
            return FetchResult(status=FetchStatus.FOUND, participant=found)

    found_html = _html_fallback_find_participant(html, target_name)
    if found_html is not None:
        return FetchResult(status=FetchStatus.FOUND, participant=found_html)

    rsc_found = _rsc_fallback_find_participant(
        session=session,
        url=url,
        timeout_seconds=timeout_seconds,
        target_name=target_name,
    )
    if rsc_found is not None:
        return FetchResult(status=FetchStatus.FOUND, participant=rsc_found)

    return FetchResult(status=FetchStatus.NOT_FOUND, participant=None)


def _rsc_fallback_find_participant(
    *,
    session: requests.Session,
    url: str,
    timeout_seconds: int,
    target_name: str,
) -> Optional[Participant]:
    target_norm = _normalize_name(target_name)
    if not target_norm:
        return None

    try:
        resp = session.get(
            url,
            timeout=timeout_seconds,
            headers={
                "Accept": "text/x-component,*/*",
                "RSC": "1",
            },
        )
        if resp.status_code != 200:
            return None

        content_type = resp.headers.get("content-type", "").lower()
        if "text/x-component" not in content_type:
            return None

        for line in resp.text.splitlines():
            if ":" not in line:
                continue
            _, rest = line.split(":", 1)
            rest = rest.strip()
            if not rest or rest[0] not in "[{":
                continue
            try:
                obj = json.loads(rest)
            except Exception:
                continue

            participants = _extract_participants_from_json(obj)
            found = _find_by_name(participants, target_name)
            if found is not None:
                return found

        return None
    except requests.RequestException:
        return None
