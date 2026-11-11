"""The Telegram bot: answers /start and the "📊 Statistika" button with the report. Only for the admins in TELEGRAM_ADMIN_IDS;
anybody else is told their own id (so the owner can find theirs and put it into .env). Long polling: no webhook, no open port."""

import json
import logging
import os
import time
import urllib.error
import urllib.request

from .report import build_report

log = logging.getLogger("stats.bot")

BUTTON = "📊 Statistika"
KEYBOARD = {"keyboard": [[{"text": BUTTON}]], "resize_keyboard": True}


def admin_ids() -> set[int]:
    out = set()
    for part in os.environ.get("TELEGRAM_ADMIN_IDS", "").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return out


class Telegram:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, payload: dict, timeout: float = 30) -> dict:
        req = urllib.request.Request(self.base + method, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def send(self, chat_id: int, text: str) -> None:
        self.call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": KEYBOARD, "disable_web_page_preview": True})


def reply_for(chat_id: int, text: str, admins: set[int]) -> str | None:
    """What to answer to a message (None = nothing)."""
    t = (text or "").strip()
    if not (t.startswith("/start") or t.startswith("/stat") or t == BUTTON):
        return None
    if chat_id not in admins:
        return (
            "Bu bot faqat admin uchun.\n"
            f"Sizning ID: <code>{chat_id}</code>\n"
            "Agar admin siz bo‘lsangiz, shu raqamni serverdagi .env ga TELEGRAM_ADMIN_IDS sifatida yozing."
        )
    return build_report()


def handle(tg: Telegram, update: dict, admins: set[int]) -> None:
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return
    answer = reply_for(chat_id, msg.get("text", ""), admins)
    if answer:
        tg.send(chat_id, answer)


def run_forever(token: str) -> None:
    tg = Telegram(token)
    offset = 0
    log.info("stats bot started")
    while True:
        try:
            res = tg.call("getUpdates", {"timeout": 50, "offset": offset, "allowed_updates": ["message"]}, timeout=60)
            admins = admin_ids()
            for upd in res.get("result", []):
                offset = max(offset, upd.get("update_id", 0) + 1)
                try:
                    handle(tg, upd, admins)
                except Exception:  # one bad update must not stop the bot
                    log.exception("update failed")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            log.warning("telegram unreachable, retrying in 5 s")
            time.sleep(5)
