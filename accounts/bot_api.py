"""API for the Telegram bot (game_bot), only with the shared X-Bot-Key header: Telegram sign-up, the site login confirmation,
login/password, premium payments, the admins, the morning message recipients and the statistics."""

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .auth import body, bot_required, env_admin, err, me, profile_of
from .models import ROLE_ADMIN, LoginCode, Payment, Profile, SiteSettings
from .services import decide_payment, set_credentials, stats_text, telegram_profile


def _tg(d: dict) -> int | None:
    v = d.get("tg_id")
    return v if isinstance(v, int) and v > 0 else None


def _profile(tg_id: int) -> Profile | None:
    return Profile.objects.select_related("user").filter(telegram_id=tg_id).first()


def _is_admin(tg_id: int | None) -> bool:
    if tg_id is None:
        return False
    if env_admin(tg_id):
        return True
    p = _profile(tg_id)
    return p is not None and p.is_admin


@csrf_exempt
@require_POST
@bot_required
def start(request: HttpRequest) -> JsonResponse:
    """/start: the Telegram user gets (or already has) an account; payload "login_<code>" confirms a site sign-in."""
    d = body(request)
    tg = _tg(d)
    if tg is None:
        return err("tg_id")
    p, created = telegram_profile(tg, d.get("first_name"), d.get("last_name"), d.get("username"), bot_active=True)
    if p is None:
        return err("retry", 409)
    login = None
    payload = str(d.get("payload", "") or "")
    if payload.startswith("login_"):
        lc = LoginCode.objects.filter(code=payload[6:46]).first()
        if lc is None or lc.expired:
            login = "expired"
        else:
            lc.user = p.user
            lc.save(update_fields=["user"])
            login = "ok"
    return JsonResponse({"ok": True, "created": created, "login": login, "me": me(p.user), "isAdmin": _is_admin(tg)})


@csrf_exempt
@require_POST
@bot_required
def credentials(request: HttpRequest) -> JsonResponse:
    tg = _tg(body(request))
    p = _profile(tg) if tg else None
    if p is None:
        return err("Avval /start bosing", 404)
    username, password = set_credentials(p.user)
    return JsonResponse({"ok": True, "username": username, "password": password})


@require_GET
@bot_required
def account(request: HttpRequest) -> JsonResponse:
    tg = request.GET.get("tg_id", "")
    p = _profile(int(tg)) if tg.isdigit() else None
    if p is None:
        return err("not found", 404)
    return JsonResponse({"ok": True, "me": me(p.user), "isAdmin": _is_admin(p.telegram_id)})


@require_GET
@bot_required
def config(request: HttpRequest) -> JsonResponse:
    s = SiteSettings.get()
    return JsonResponse({"ok": True, "monthlyPrice": s.monthly_price, "cardNumber": s.card_number, "cardHolder": s.card_holder, "siteUrl": settings.SITE_URL})


@csrf_exempt
@require_POST
@bot_required
def payment(request: HttpRequest) -> JsonResponse:
    """A receipt photo was sent: a pending payment for 1 month at the current price."""
    d = body(request)
    tg = _tg(d)
    file_id = str(d.get("file_id", ""))[:255]
    p = _profile(tg) if tg else None
    if p is None or not file_id:
        return err("Avval /start bosing", 404)
    if Payment.objects.filter(user=p.user, status=Payment.PENDING).count() >= 3:
        return err("Oldingi cheklaringiz hali tekshirilmoqda", 429)
    pay = Payment.objects.create(user=p.user, amount=SiteSettings.get().monthly_price, days=30, receipt_file_id=file_id)
    return JsonResponse({"ok": True, "id": pay.id, "user": p.display(), "username": p.user.username, "amount": pay.amount, "days": pay.days})


@csrf_exempt
@require_POST
@bot_required
def payment_decide(request: HttpRequest, payment_id: int) -> JsonResponse:
    d = body(request)
    admin_tg = d.get("admin_tg_id")
    if not isinstance(admin_tg, int) or not _is_admin(admin_tg):
        return err("Ruxsat yo‘q", 403)
    before = Payment.objects.filter(pk=payment_id).values_list("status", flat=True).first()
    who = _profile(admin_tg)
    pay = decide_payment(payment_id, d.get("approve") is True, f"bot: {who.display() if who else admin_tg}")
    if pay is None:
        return err("Topilmadi", 404)
    p = profile_of(pay.user)
    return JsonResponse(
        {
            "ok": True,
            "status": pay.status,
            "already": before != Payment.PENDING,
            "decidedBy": pay.decided_by,
            "userTgId": p.telegram_id,
            "premiumUntil": timezone.localtime(p.premium_until).strftime("%d.%m.%Y") if p.premium_until else None,
        }
    )


@require_GET
@bot_required
def admins(request: HttpRequest) -> JsonResponse:
    ids = set(settings.ADMIN_TELEGRAM_IDS)
    ids.update(Profile.objects.filter(role=ROLE_ADMIN, telegram_id__isnull=False).values_list("telegram_id", flat=True))
    return JsonResponse({"ok": True, "ids": sorted(ids)})


@require_GET
@bot_required
def recipients(request: HttpRequest) -> JsonResponse:
    ids = list(Profile.objects.filter(bot_active=True, telegram_id__isnull=False).values_list("telegram_id", flat=True))
    return JsonResponse({"ok": True, "ids": ids})


@csrf_exempt
@require_POST
@bot_required
def blocked(request: HttpRequest) -> JsonResponse:
    tg = _tg(body(request))
    if tg:
        Profile.objects.filter(telegram_id=tg).update(bot_active=False)
    return JsonResponse({"ok": True})


@require_GET
@bot_required
def bot_stats(request: HttpRequest) -> JsonResponse:
    tg = request.GET.get("tg_id", "")
    if not tg.isdigit() or not _is_admin(int(tg)):
        return err("Ruxsat yo‘q", 403)
    return JsonResponse({"ok": True, "text": stats_text()})
