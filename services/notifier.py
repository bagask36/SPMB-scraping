from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Optional


MONTH_ID = [
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
]


def format_wib(dt: datetime) -> str:
    return f"{dt.day:02d} {MONTH_ID[dt.month - 1]} {dt.year} {dt.hour:02d}:{dt.minute:02d} WIB"


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]
    mail_from: str
    notification_email: str

    @staticmethod
    def from_env() -> "SmtpConfig":
        host = (os.environ.get("SMTP_HOST") or "").strip()
        port_raw = (os.environ.get("SMTP_PORT") or "").strip()
        username = (os.environ.get("SMTP_USERNAME") or "").strip() or None
        password = (os.environ.get("SMTP_PASSWORD") or "").strip() or None
        mail_from = (os.environ.get("SMTP_FROM") or "").strip()
        notification_email = (os.environ.get("NOTIFICATION_EMAIL") or "").strip()

        if not host:
            raise ValueError("SMTP_HOST belum di-set")
        if not port_raw:
            raise ValueError("SMTP_PORT belum di-set")
        try:
            port = int(port_raw)
        except ValueError as e:
            raise ValueError("SMTP_PORT harus angka") from e
        if not mail_from:
            raise ValueError("SMTP_FROM belum di-set")
        if not notification_email:
            raise ValueError("NOTIFICATION_EMAIL belum di-set")

        return SmtpConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            mail_from=mail_from,
            notification_email=notification_email,
        )


class EmailNotifier:
    def __init__(self, config: SmtpConfig, timeout_seconds: int = 20) -> None:
        self._config = config
        self._timeout_seconds = timeout_seconds

    def send_rank_change(
        self,
        *,
        name: str,
        old_rank: int,
        new_rank: int,
        checked_at_wib: datetime,
    ) -> None:
        delta = abs(new_rank - old_rank)
        if new_rank < old_rank:
            status = f"NAIK {delta} peringkat"
        elif new_rank > old_rank:
            status = f"TURUN {delta} peringkat"
        else:
            status = "TIDAK BERUBAH"

        msg = EmailMessage()
        msg["Subject"] = "Perubahan Ranking SPMB"
        msg["From"] = self._config.mail_from
        msg["To"] = self._config.notification_email
        body = "\n".join(
            [
                f"Nama Peserta: {name}",
                "",
                f"Ranking Lama: {old_rank}",
                f"Ranking Baru: {new_rank}",
                "",
                f"Status: {status}",
                "",
                f"Waktu: {format_wib(checked_at_wib)}",
            ]
        )
        msg.set_content(body)

        with smtplib.SMTP(
            self._config.host, self._config.port, timeout=self._timeout_seconds
        ) as smtp:
            smtp.ehlo()
            try:
                if smtp.has_extn("starttls"):
                    smtp.starttls()
                    smtp.ehlo()
            except smtplib.SMTPException:
                pass

            if self._config.username and self._config.password:
                smtp.login(self._config.username, self._config.password)
            smtp.send_message(msg)
