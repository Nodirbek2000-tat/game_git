"""Telegram Mini App: the site opened inside Telegram gets `initData`, signed by Telegram with the bot's token. A valid signature
proves who the user is, so the Mini App signs in by itself (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)."""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

# how old the signed data may be (seconds): a Mini App opened yesterday must be reopened
MAX_AGE = 24 * 3600


def verify_init_data(init_data: str, bot_token: str, now: float | None = None) -> dict | None:
    """The Telegram user (dict with id, first_name, ...) when `init_data` is genuine and fresh, else None."""
    if not init_data or not bot_token or len(init_data) > 4096:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    data = dict(pairs)
    given = data.pop("hash", "")
    if not given:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, given):
        return None
    try:
        auth_date = int(data.get("auth_date", "0"))
        user = json.loads(data.get("user", "null"))
    except (ValueError, TypeError):
        return None
    if (now or time.time()) - auth_date > MAX_AGE or not isinstance(user, dict) or not isinstance(user.get("id"), int):
        return None
    return user
