"""Minimal first-party SMTP adapter; reset emails contain only a short-lived token."""
from __future__ import annotations

import asyncio
from email.message import EmailMessage
import os
import smtplib
from urllib.parse import urlencode


class SMTPMailer:
    def __init__(self, *, host: str, port: int, username: str, password: str,
                 sender: str, reset_url: str):
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self.sender = sender
        self.reset_url = reset_url

    async def send_password_reset(self, email: str, reset_token: str) -> None:
        await asyncio.to_thread(self._send, email, reset_token)

    def _send(self, email: str, reset_token: str) -> None:
        link = self.reset_url + ("&" if "?" in self.reset_url else "?") + urlencode({"token": reset_token})
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = email
        message["Subject"] = "膳算账户密码重置"
        message.set_content(
            "我们收到一项密码重置请求。请在 15 分钟内使用以下链接设置新密码：\n\n"
            f"{link}\n\n如果不是你本人操作，请忽略此邮件。"
        )
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(self.username, self._password)
            smtp.send_message(message)


def mailer_from_env() -> SMTPMailer | None:
    values = {key: os.environ.get(key, "").strip() for key in (
        "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_SENDER", "PASSWORD_RESET_URL"
    )}
    if not any(values.values()):
        return None
    if not all(values.values()):
        raise ValueError("SMTP reset-mail configuration is incomplete")
    if not values["SMTP_PORT"].isdigit() or not values["PASSWORD_RESET_URL"].startswith("https://"):
        raise ValueError("SMTP port or password-reset URL is invalid")
    return SMTPMailer(
        host=values["SMTP_HOST"], port=int(values["SMTP_PORT"]),
        username=values["SMTP_USERNAME"], password=values["SMTP_PASSWORD"],
        sender=values["SMTP_SENDER"], reset_url=values["PASSWORD_RESET_URL"],
    )
