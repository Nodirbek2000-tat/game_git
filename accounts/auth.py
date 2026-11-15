"""Small helpers shared by the views: JSON in/out, the device token ("Authorization: Bearer ..."), roles, device limits."""

import hmac
import json
import re
from datetime import timedelta
from functools import wraps
from typing import Any, Callable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest, JsonResponse
from django.utils import timezone

from .models import ROLE_ADMIN, ROLE_BOGCHA, Device, Profile, hash_token

User = get_user_model()

USERNAME = re.compile(r"^[a-zA-Z0-9_.]{3,30}$")
TOUCH_EVERY = timedelta(minutes=5)


class LimitError(Exception):
    """A kindergarten account has all its devices in use."""


def body(request: HttpRequest) -> dict[str, Any]:
    if len(request.body) > 16_384:
        return {}
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def err(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def profile_of(user) -> Profile:
    p = getattr(user, "profile", None)
    if p is None:
        p, _ = Profile.objects.get_or_create(user=user)
    return p


def me(user) -> dict[str, Any]:
    p = profile_of(user)
    return {
        "id": user.id,
        "username": user.username,
        "name": p.display(),
        "role": "admin" if p.is_admin else p.role,
        "isAdmin": p.is_admin,
        "premium": p.is_premium,
        "premiumUntil": p.premium_until.isoformat() if p.premium_until else None,
        "telegram": p.telegram_id is not None,
        "devices": user.devices.count(),
        "deviceLimit": p.device_limit,
    }


def issue_device(user, name: str) -> str:
    """A new signed-in device. Over the limit: an ordinary account drops its oldest device, a kindergarten account is refused."""
    p = profile_of(user)
    limit = p.device_limit
    devices = list(user.devices.order_by("last_seen"))
    if len(devices) >= limit:
        if p.role == ROLE_BOGCHA:
            raise LimitError()
        for d in devices[: len(devices) - limit + 1]:
            d.delete()
    _, raw = Device.issue(user, name)
    return raw


def device_name(request: HttpRequest) -> str:
    ua = request.META.get("HTTP_USER_AGENT", "")
    for key, label in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"), ("Macintosh", "Mac"), ("Linux", "Linux")):
        if key in ua:
            return label
    return "Qurilma"


def device_from(request: HttpRequest) -> Device | None:
    h = request.META.get("HTTP_AUTHORIZATION", "")
    if not h.startswith("Bearer "):
        return None
    raw = h[7:].strip()
    if not raw or len(raw) > 100:
        return None
    d = Device.objects.select_related("user", "user__profile").filter(key=hash_token(raw)).first()
    if d is None or not d.user.is_active:
        return None
    now = timezone.now()
    if now - d.last_seen > TOUCH_EVERY:
        Device.objects.filter(pk=d.pk).update(last_seen=now)
    return d


def auth_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapper(request: HttpRequest, *a, **kw):
        d = device_from(request)
        if d is None:
            return err("Kirish kerak", 401)
        request.device = d
        request.account = d.user
        return view(request, *a, **kw)

    return wrapper


def admin_required(view: Callable) -> Callable:
    @wraps(view)
    @auth_required
    def wrapper(request: HttpRequest, *a, **kw):
        if not profile_of(request.account).is_admin:
            return err("Ruxsat yo‘q", 403)
        return view(request, *a, **kw)

    return wrapper


def bot_required(view: Callable) -> Callable:
    """The Telegram bot (game_bot) calls with the shared key; without a configured key the bot API is off."""

    @wraps(view)
    def wrapper(request: HttpRequest, *a, **kw):
        key = settings.BOT_API_KEY
        given = request.META.get("HTTP_X_BOT_KEY", "")
        if not key or not hmac.compare_digest(given, key):
            return err("forbidden", 403)
        return view(request, *a, **kw)

    return wrapper


def env_admin(telegram_id: int | None) -> bool:
    return telegram_id is not None and telegram_id in settings.ADMIN_TELEGRAM_IDS


def make_admin_if_listed(p: Profile) -> None:
    if env_admin(p.telegram_id) and p.role != ROLE_ADMIN:
        p.role = ROLE_ADMIN
        p.save(update_fields=["role"])
