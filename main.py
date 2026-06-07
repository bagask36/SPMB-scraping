from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from services.notifier import EmailNotifier, SmtpConfig
from services.scraper import FetchStatus, fetch_participant
from services.storage import State, isoformat_now, load_state, save_state


DEFAULT_TARGET_NAME = "Kanaia Pramesthi Nareswari"


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def _get_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    return value


def main() -> int:
    _setup_logging()
    wib = ZoneInfo("Asia/Jakarta")

    target_name = _get_env("TARGET_NAME") or DEFAULT_TARGET_NAME

    checked_at = datetime.now(tz=wib)
    checked_at_iso = isoformat_now(checked_at)

    previous = load_state()
    logging.info(
        "Mulai cek | target=%s | prev_rank=%s | prev_score=%s",
        target_name,
        previous.rank,
        previous.score,
    )

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
    )

    if previous.rank is None:
        logging.info("State awal belum ada. Simpan state tanpa kirim email.")
        save_state(current_state)
        return 0

    if participant.rank == previous.rank:
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
            )
        )
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise
