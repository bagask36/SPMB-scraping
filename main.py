from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from services.notifier import EmailNotifier, SmtpConfig
from services.scraper import FetchStatus, fetch_participant, fetch_participant_by_nisn
from services.storage import State, isoformat_now, load_state, save_state


DEFAULT_TARGET_NAME = "Kanaia Pramesthi Nareswari"
DEFAULT_DOTENV_PATH = Path(".env")
DEFAULT_UPDATE_EMAIL_INTERVAL_MINUTES = 120


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def _get_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    return value


def _load_dotenv(path: Path = DEFAULT_DOTENV_PATH) -> None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return

    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        key, value = s.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _get_env_int(name: str, default: int) -> int:
    raw = _get_env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _should_send_periodic_email(
    previous: State,
    checked_at: datetime,
    interval_minutes: int,
) -> bool:
    if interval_minutes <= 0:
        return True
    last_sent = _parse_iso_datetime(previous.last_update_email)
    if last_sent is None:
        return True
    return checked_at >= last_sent + timedelta(minutes=interval_minutes)


def main() -> int:
    _setup_logging()
    _load_dotenv()
    wib = ZoneInfo("Asia/Jakarta")

    target_name = _get_env("TARGET_NAME") or DEFAULT_TARGET_NAME
    target_nisn = _get_env("TARGET_NISN")
    send_every_check = _get_env("SEND_EVERY_CHECK").lower() in {"1", "true", "yes", "y", "on"}
    update_email_interval_minutes = _get_env_int(
        "UPDATE_EMAIL_INTERVAL_MINUTES",
        DEFAULT_UPDATE_EMAIL_INTERVAL_MINUTES,
    )

    checked_at = datetime.now(tz=wib)
    checked_at_iso = isoformat_now(checked_at)

    previous = load_state()
    logging.info(
        "Mulai cek | target=%s | prev_rank=%s | prev_score=%s",
        target_name,
        previous.rank,
        previous.score,
    )

    if target_nisn:
        logging.info("Mode cek: NISN | nisn=%s", target_nisn)
        result = fetch_participant_by_nisn(target_nisn)
    else:
        logging.info("Mode cek: Nama (fallback) | catatan=halaman sekolah bersifat dinamis")
        result = fetch_participant(target_name)
    if result.status == FetchStatus.ERROR:
        logging.error(
            "Gagal cek website | waktu=%s | error=%s",
            checked_at_iso,
            result.error or "-",
        )
        save_state(
            State(
                name=previous.name or target_name,
                rank=previous.rank,
                score=previous.score,
                last_check=checked_at_iso,
                last_update_email=previous.last_update_email,
            )
        )
        return 0

    if result.status == FetchStatus.NOT_FOUND or result.participant is None:
        logging.warning("Peserta tidak ditemukan | waktu=%s | target=%s", checked_at_iso, target_name)
        save_state(
            State(
                name=previous.name or target_name,
                rank=previous.rank,
                score=previous.score,
                last_check=checked_at_iso,
                last_update_email=previous.last_update_email,
            )
        )
        return 0

    participant = result.participant

    logging.info(
        "Hasil cek | waktu=%s | name=%s | rank=%s | score=%s",
        checked_at_iso,
        participant.name,
        participant.rank,
        participant.score,
    )

    current_state = State(
        name=participant.name,
        rank=participant.rank,
        score=participant.score,
        last_check=checked_at_iso,
        last_update_email=previous.last_update_email,
    )

    if previous.rank is None:
        if send_every_check and _should_send_periodic_email(previous, checked_at, update_email_interval_minutes):
            logging.info("Mode email: KIRIM BERKALA | alasan=state_awal | interval_menit=%s", update_email_interval_minutes)
            try:
                notifier = EmailNotifier(SmtpConfig.from_env())
                notifier.send_rank_update(
                    name=participant.name,
                    rank=int(participant.rank),
                    score=participant.score,
                    checked_at_wib=checked_at,
                )
                logging.info("Email update terkirim | to=%s", os.environ.get("NOTIFICATION_EMAIL"))
                current_state = State(
                    name=current_state.name,
                    rank=current_state.rank,
                    score=current_state.score,
                    last_check=current_state.last_check,
                    last_update_email=checked_at_iso,
                )
            except Exception as e:
                logging.error("Gagal kirim email update | error=%s", e)

        logging.info("State awal belum ada. Simpan state.")
        save_state(current_state)
        return 0

    if participant.rank == previous.rank:
        if send_every_check and _should_send_periodic_email(previous, checked_at, update_email_interval_minutes):
            logging.info(
                "Mode email: KIRIM BERKALA | prev=%s | now=%s | interval_menit=%s",
                previous.rank,
                participant.rank,
                update_email_interval_minutes,
            )
            try:
                notifier = EmailNotifier(SmtpConfig.from_env())
                notifier.send_rank_update(
                    name=participant.name,
                    rank=int(participant.rank),
                    score=participant.score,
                    checked_at_wib=checked_at,
                )
                logging.info("Email update terkirim | to=%s", os.environ.get("NOTIFICATION_EMAIL"))
                current_state = State(
                    name=current_state.name,
                    rank=current_state.rank,
                    score=current_state.score,
                    last_check=current_state.last_check,
                    last_update_email=checked_at_iso,
                )
            except Exception as e:
                logging.error("Gagal kirim email update | error=%s", e)
        elif send_every_check:
            logging.info(
                "Email update ditunda | alasan=belum_2_jam | last_sent=%s | interval_menit=%s",
                previous.last_update_email,
                update_email_interval_minutes,
            )
        else:
            logging.info(
                "Ranking tidak berubah | prev=%s | now=%s | email=SKIP",
                previous.rank,
                participant.rank,
            )
        save_state(current_state)
        return 0

    old_rank = int(previous.rank)
    new_rank = int(participant.rank)
    delta = abs(new_rank - old_rank)
    status = "NAIK" if new_rank < old_rank else "TURUN"

    logging.info(
        "Ranking berubah | prev=%s | now=%s | status=%s | delta=%s",
        old_rank,
        new_rank,
        status,
        delta,
    )

    try:
        notifier = EmailNotifier(SmtpConfig.from_env())
        notifier.send_rank_change(
            name=participant.name,
            old_rank=old_rank,
            new_rank=new_rank,
            checked_at_wib=checked_at,
        )
        logging.info("Email notifikasi terkirim | to=%s", os.environ.get("NOTIFICATION_EMAIL"))
        save_state(current_state)
        return 0
    except Exception as e:
        logging.error("Gagal kirim email | error=%s", e)
        save_state(
            State(
                name=previous.name or participant.name,
                rank=previous.rank,
                score=previous.score,
                last_check=checked_at_iso,
                last_update_email=previous.last_update_email,
            )
        )
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise
