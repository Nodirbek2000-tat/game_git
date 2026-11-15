"""Site API: sign in (password or Telegram), the current user, the public config and the admin panel. There is no sign-up here:
a new account is made by the Telegram bot (/start), a kindergarten account by an admin."""

import secrets

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .auth import USERNAME, LimitError, User, admin_required, auth_required, body, device_name, err, issue_device, me, profile_of
from .models import ROLE_ADMIN, ROLE_BOGCHA, ROLE_USER, ROLES, LoginCode, Payment, SiteSettings
from .services import create_bogcha, decide_payment, new_password, stats, telegram_profile
from .webapp import verify_init_data

LIMIT_MSG = "Bu bog‘cha akkauntida 10 ta qurilma ulangan. Admin bilan bog‘laning."
# wrong passwords allowed per login and per address in 15 minutes
FAILS_MAX = 8
FAILS_TTL = 15 * 60


def _signed_in(request: HttpRequest, user) -> JsonResponse:
    try:
        token = issue_device(user, device_name(request))
    except LimitError:
        return err(LIMIT_MSG, 409)
    return JsonResponse({"ok": True, "token": token, "me": me(user)})


def _ip(request: HttpRequest) -> str:
    return (request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "")[:64]


# ----------------------------------------------------------------------------------------------- public


@require_GET
def config(request: HttpRequest) -> JsonResponse:
    s = SiteSettings.get()
    return JsonResponse(
        {
            "freeGames": s.free_games,
            "monthlyPrice": s.monthly_price,
            "bogchaPhone": s.bogcha_phone,
            "botUsername": settings.BOT_USERNAME,
        }
    )


@csrf_exempt
@require_POST
def login(request: HttpRequest) -> JsonResponse:
    d = body(request)
    username = str(d.get("username", "")).strip()[:30]
    password = str(d.get("password", ""))[:128]
    key = f"fails:{username.lower()}:{_ip(request)}"
    if (cache.get(key) or 0) >= FAILS_MAX:
        return err("Ko‘p marta noto‘g‘ri kiritildi. 15 daqiqadan keyin urinib ko‘ring.", 429)
    match = User.objects.filter(username__iexact=username).first()
    user = authenticate(request, username=match.username, password=password) if match else None
    if user is None:
        cache.set(key, (cache.get(key) or 0) + 1, FAILS_TTL)
        return err("Login yoki parol noto‘g‘ri", 401)
    cache.delete(key)
    return _signed_in(request, user)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def telegram(request: HttpRequest) -> JsonResponse:
    """POST: a new login code + the bot link. GET ?code=: pending (202) / signed in (200, once) / expired (410)."""
    if request.method == "POST":
        code = secrets.token_urlsafe(18)
        LoginCode.objects.create(code=code)
        return JsonResponse({"ok": True, "code": code, "url": f"https://t.me/{settings.BOT_USERNAME}?start=login_{code}"})
    code = request.GET.get("code", "")[:40]
    lc = LoginCode.objects.select_related("user").filter(code=code).first()
    if lc is None or lc.expired:
        if lc:
            lc.delete()
        return err("Muddat tugadi, qaytadan bosing", 410)
    if lc.user is None:
        return JsonResponse({"ok": True, "pending": True}, status=202)
    user = lc.user
    lc.delete()
    return _signed_in(request, user)


@csrf_exempt
@require_POST
def webapp(request: HttpRequest) -> JsonResponse:
    """Inside the Telegram Mini App: sign in with Telegram's signed initData (a new Telegram user gets an account)."""
    user = verify_init_data(str(body(request).get("initData", "")), settings.TELEGRAM_BOT_TOKEN)
    if user is None:
        return err("Telegram ma’lumoti tasdiqlanmadi", 401)
    p, _ = telegram_profile(user["id"], user.get("first_name"), user.get("last_name"), user.get("username"))
    if p is None:
        return err("Qayta urinib ko‘ring", 409)
    return _signed_in(request, p.user)


@csrf_exempt
@require_POST
@auth_required
def logout(request: HttpRequest) -> JsonResponse:
    request.device.delete()
    return JsonResponse({"ok": True})


@require_GET
@auth_required
def whoami(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True, "me": me(request.account)})


# ----------------------------------------------------------------------------------------------- admin panel


@require_GET
@admin_required
def admin_stats(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True, **stats()})


def _row(user) -> dict:
    p = profile_of(user)
    m = me(user)
    m.update({"telegramUsername": p.telegram_username, "created": p.created.isoformat(), "lastSeen": None})
    last = user.devices.order_by("-last_seen").first()
    if last:
        m["lastSeen"] = last.last_seen.isoformat()
    return m


@require_GET
@admin_required
def admin_users(request: HttpRequest) -> JsonResponse:
    q = request.GET.get("q", "").strip()[:60]
    role = request.GET.get("role", "")
    page = max(1, int(request.GET.get("page", "1") or 1))
    users = User.objects.select_related("profile").prefetch_related("devices").order_by("-id")
    if q:
        users = users.filter(Q(username__icontains=q) | Q(profile__name__icontains=q) | Q(profile__telegram_username__icontains=q))
    if role in dict(ROLES):
        users = users.filter(profile__role=role)
    total = users.count()
    size = 30
    rows = [_row(u) for u in users[(page - 1) * size : page * size]]
    return JsonResponse({"ok": True, "total": total, "page": page, "pages": max(1, (total + size - 1) // size), "users": rows})


@csrf_exempt
@require_POST
@admin_required
def admin_user(request: HttpRequest, user_id: int) -> JsonResponse:
    """Change one user: {role, premiumDays (+ / -), premiumClear, resetDevices, newPassword: true}."""
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return err("Topilmadi", 404)
    d = body(request)
    p = profile_of(user)
    out: dict = {}
    role = d.get("role")
    if role in (ROLE_USER, ROLE_BOGCHA, ROLE_ADMIN):
        if user == request.account and role != ROLE_ADMIN:
            return err("O‘zingizdan adminlikni ololmaysiz")
        p.role = role
    days = d.get("premiumDays")
    if isinstance(days, int) and -3650 <= days <= 3650 and days != 0:
        p.add_premium(days)
    if d.get("premiumClear") is True:
        p.premium_until = None
    p.save()
    if d.get("resetDevices") is True:
        user.devices.all().delete()
    if d.get("newPassword") is True:
        pw = new_password(10 if p.role == ROLE_BOGCHA else 8)
        user.set_password(pw)
        user.save(update_fields=["password"])
        out["password"] = pw
    return JsonResponse({"ok": True, "user": _row(user), **out})


@csrf_exempt
@require_POST
@admin_required
def admin_bogcha(request: HttpRequest) -> JsonResponse:
    d = body(request)
    name = str(d.get("name", "")).strip()
    if not name:
        return err("Bog‘cha nomini yozing")
    days = d.get("premiumDays") if isinstance(d.get("premiumDays"), int) else 0
    user, password = create_bogcha(name, str(d.get("username", "")).strip() or None, max(0, min(3650, days)))
    return JsonResponse({"ok": True, "username": user.username, "password": password, "user": _row(user)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@admin_required
def admin_settings(request: HttpRequest) -> JsonResponse:
    s = SiteSettings.get()
    if request.method == "POST":
        d = body(request)
        if isinstance(d.get("monthlyPrice"), int) and 0 <= d["monthlyPrice"] <= 100_000_000:
            s.monthly_price = d["monthlyPrice"]
        for key, field, n in (("cardNumber", "card_number", 40), ("cardHolder", "card_holder", 120), ("bogchaPhone", "bogcha_phone", 40)):
            if isinstance(d.get(key), str):
                setattr(s, field, d[key].strip()[:n])
        if isinstance(d.get("freeGames"), list):
            s.free_games = [g for g in d["freeGames"] if isinstance(g, str) and USERNAME.match(g.replace("-", "_"))][:100]
        s.save()
    return JsonResponse(
        {"ok": True, "monthlyPrice": s.monthly_price, "cardNumber": s.card_number, "cardHolder": s.card_holder, "bogchaPhone": s.bogcha_phone, "freeGames": s.free_games}
    )


@require_GET
@admin_required
def admin_payments(request: HttpRequest) -> JsonResponse:
    status = request.GET.get("status", Payment.PENDING)
    qs = Payment.objects.select_related("user", "user__profile").order_by("-created")
    if status in (Payment.PENDING, Payment.APPROVED, Payment.REJECTED):
        qs = qs.filter(status=status)
    rows = [
        {"id": p.id, "user": profile_of(p.user).display(), "userId": p.user_id, "amount": p.amount, "days": p.days, "status": p.status, "created": p.created.isoformat(), "decidedBy": p.decided_by}
        for p in qs[:100]
    ]
    return JsonResponse({"ok": True, "payments": rows})


@csrf_exempt
@require_POST
@admin_required
def admin_payment(request: HttpRequest, payment_id: int) -> JsonResponse:
    approve = body(request).get("approve") is True
    pay = decide_payment(payment_id, approve, f"sayt: {request.account.username}")
    if pay is None:
        return err("Topilmadi", 404)
    return JsonResponse({"ok": True, "status": pay.status})
