from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from html import escape
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
    return f"{dt.day:02d} {MONTH_ID[dt.month - 1]} {dt.year} {dt.hour:02d}:{dt.minute:02d} GMT+07"


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]
    mail_from: str
    notification_emails: list[str]

    @staticmethod
    def from_env() -> "SmtpConfig":
        host = (os.environ.get("SMTP_HOST") or "").strip()
        port_raw = (os.environ.get("SMTP_PORT") or "").strip()
        username = (os.environ.get("SMTP_USERNAME") or "").strip() or None
        password = (os.environ.get("SMTP_PASSWORD") or "").strip() or None
        mail_from = (os.environ.get("SMTP_FROM") or "").strip()
        notification_email_raw = (os.environ.get("NOTIFICATION_EMAIL") or "").strip()

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
        if not notification_email_raw:
            raise ValueError("NOTIFICATION_EMAIL belum di-set")

        parts = (
            notification_email_raw.replace(";", ",")
            .replace("\n", ",")
            .replace("\t", ",")
            .split(",")
        )
        notification_emails = [p.strip() for p in parts if p.strip()]
        if not notification_emails:
            raise ValueError("NOTIFICATION_EMAIL belum di-set")

        return SmtpConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            mail_from=mail_from,
            notification_emails=notification_emails,
        )


class EmailNotifier:
    def __init__(self, config: SmtpConfig, timeout_seconds: int = 20) -> None:
        self._config = config
        self._timeout_seconds = timeout_seconds

    def send_rank_update(
        self,
        *,
        name: str,
        rank: int,
        score: Optional[float],
        checked_at_wib: datetime,
    ) -> None:
        score_text = f"{score:.2f}" if score is not None else "-"

        msg = EmailMessage()
        msg["Subject"] = "Update Ranking SPMB"
        msg["From"] = self._config.mail_from
        msg["To"] = ", ".join(self._config.notification_emails)

        text_body = "\n".join(
            [
                f"Nama Peserta: {name}",
                "",
                f"Ranking Saat Ini: {rank}",
                f"Skor: {score_text}",
                "",
                f"Waktu: {format_wib(checked_at_wib)}",
            ]
        )
        msg.set_content(text_body)

        html_body = f"""\
<!doctype html>
<html lang="id">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body style="margin:0; padding:0; background:#f6f7fb; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; color:#111827;">
    <div style="max-width:640px; margin:0 auto; padding:24px;">
      <div style="padding:18px 20px; background:#111827; border-radius:16px 16px 0 0;">
        <div style="font-size:13px; letter-spacing:0.08em; text-transform:uppercase; color:#9CA3AF;">SPMB Jawa Barat</div>
        <div style="margin-top:6px; font-size:20px; font-weight:700; color:#FFFFFF;">Update Ranking SPMB</div>
      </div>

      <div style="background:#ffffff; border-radius:0 0 16px 16px; border:1px solid #e5e7eb; border-top:none; padding:20px;">
        <div style="margin-top:2px; color:#6B7280; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;">Nama Peserta</div>
        <div style="margin-top:6px; font-size:18px; font-weight:700; color:#111827;">{escape(name)}</div>

        <div style="margin-top:18px; display:flex; gap:12px; flex-wrap:wrap;">
          <div style="flex:1 1 240px; padding:14px; border:1px solid #e5e7eb; border-radius:14px; background:#FAFAFB;">
            <div style="color:#6B7280; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;">Ranking Saat Ini</div>
            <div style="margin-top:6px; font-size:26px; font-weight:900; color:#111827;">#{rank}</div>
          </div>
          <div style="flex:1 1 240px; padding:14px; border:1px solid #e5e7eb; border-radius:14px; background:#FAFAFB;">
            <div style="color:#6B7280; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;">Skor</div>
            <div style="margin-top:10px; font-size:18px; font-weight:800; color:#111827;">{escape(score_text)}</div>
          </div>
        </div>

        <div style="margin-top:18px; padding:14px; border-radius:14px; background:#F9FAFB; border:1px dashed #E5E7EB;">
          <div style="color:#6B7280; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;">Waktu Pengecekan</div>
          <div style="margin-top:6px; font-size:14px; font-weight:700; color:#111827;">{escape(format_wib(checked_at_wib))}</div>
        </div>

        <div style="margin-top:18px; color:#6B7280; font-size:12px; line-height:1.5;">
          Email ini dikirim otomatis setiap 15 menit (mode update berkala).
        </div>
      </div>
    </div>
  </body>
</html>
"""
        msg.add_alternative(html_body, subtype="html")

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
            badge_bg = "#ECFDF3"
            badge_fg = "#047857"
        elif new_rank > old_rank:
            status = f"TURUN {delta} peringkat"
            badge_bg = "#FEF2F2"
            badge_fg = "#B91C1C"
        else:
            status = "TIDAK BERUBAH"
            badge_bg = "#F3F4F6"
            badge_fg = "#374151"

        msg = EmailMessage()
        msg["Subject"] = "Perubahan Ranking SPMB"
        msg["From"] = self._config.mail_from
        msg["To"] = ", ".join(self._config.notification_emails)
        text_body = "\n".join(
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
        msg.set_content(text_body)

        html_body = f"""\
<!doctype html>
<html lang="id">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body style="margin:0; padding:0; background:#f6f7fb; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; color:#111827;">
    <div style="max-width:640px; margin:0 auto; padding:24px;">
      <div style="padding:18px 20px; background:#111827; border-radius:16px 16px 0 0;">
        <div style="font-size:13px; letter-spacing:0.08em; text-transform:uppercase; color:#9CA3AF;">SPMB Jawa Barat</div>
        <div style="margin-top:6px; font-size:20px; font-weight:700; color:#FFFFFF;">Perubahan Ranking SPMB</div>
      </div>

      <div style="background:#ffffff; border-radius:0 0 16px 16px; border:1px solid #e5e7eb; border-top:none; padding:20px;">
        <div style="display:inline-block; padding:6px 10px; border-radius:999px; background:{badge_bg}; color:{badge_fg}; font-weight:700; font-size:12px;">
          {escape(status)}
        </div>

        <div style="margin-top:14px; font-size:16px; line-height:1.4;">
          <div style="color:#6B7280; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;">Nama Peserta</div>
          <div style="margin-top:4px; font-size:18px; font-weight:700; color:#111827;">{escape(name)}</div>
        </div>

        <div style="margin-top:18px; display:flex; gap:12px; flex-wrap:wrap;">
          <div style="flex:1 1 180px; padding:14px; border:1px solid #e5e7eb; border-radius:14px; background:#FAFAFB;">
            <div style="color:#6B7280; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;">Ranking Lama</div>
            <div style="margin-top:6px; font-size:22px; font-weight:800; color:#111827;">{old_rank}</div>
          </div>
          <div style="flex:1 1 180px; padding:14px; border:1px solid #e5e7eb; border-radius:14px; background:#FAFAFB;">
            <div style="color:#6B7280; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;">Ranking Baru</div>
            <div style="margin-top:6px; font-size:22px; font-weight:800; color:#111827;">{new_rank}</div>
          </div>
          <div style="flex:1 1 180px; padding:14px; border:1px solid #e5e7eb; border-radius:14px; background:#FAFAFB;">
            <div style="color:#6B7280; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;">Selisih</div>
            <div style="margin-top:6px; font-size:22px; font-weight:800; color:#111827;">{delta}</div>
          </div>
        </div>

        <div style="margin-top:18px; padding:14px; border-radius:14px; background:#F9FAFB; border:1px dashed #E5E7EB;">
          <div style="color:#6B7280; font-size:12px; letter-spacing:0.08em; text-transform:uppercase;">Waktu Pengecekan</div>
          <div style="margin-top:6px; font-size:14px; font-weight:700; color:#111827;">{escape(format_wib(checked_at_wib))}</div>
        </div>

        <div style="margin-top:18px; color:#6B7280; font-size:12px; line-height:1.5;">
          Email ini dikirim otomatis oleh sistem monitoring ranking SPMB.
        </div>
      </div>
    </div>
  </body>
</html>
"""
        msg.add_alternative(html_body, subtype="html")

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
