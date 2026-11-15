"""The operations both the site's admin panel and the Telegram bot use."""

import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from stats.models import Play, Visit
from stats.report import GAME_TITLES, TZ, today

from .auth import USERNAME, profile_of
from .models import ROLE_ADMIN, ROLE_BOGCHA, Device, Payment, Profile

User = get_user_model()

# readable passwords: no 0/O, 1/l/I
_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


def new_password(n: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def free_username(base: str) -> str:
    base = "".join(ch for ch in base.lower() if ch.isalnum() or ch in "_.")[:24] or "user"
    if len(base) < 3:
        base = f"user_{base}"
    name, i = base, 1
    while User.objects.filter(username__iexact=name).exists():
        i += 1
        name = f"{base}{i}"
    return name


def set_credentials(user) -> tuple[str, str]:
    """A login and a NEW password for this account (the Telegram-made "tg..." login becomes a readable one)."""
    p = profile_of(user)
    if user.username.startswith("tg") and user.username[2:].isdigit():
        user.username = free_username(p.telegram_username or f"user{user.id}")
    password = new_password()
    user.set_password(password)
    user.save()
    return user.username, password


def create_bogcha(name: str, username: str | None = None, days: int = 0) -> tuple[User, str]:
    login = free_username(username or name or "bogcha")
    if username and USERNAME.match(username) and not User.objects.filter(username__iexact=username).exists():
        login = username
    password = new_password(10)
    with transaction.atomic():
        user = User.objects.create_user(username=login, password=password)
        p = Profile.objects.create(user=user, role=ROLE_BOGCHA, name=name[:120])
        if days > 0:
            p.add_premium(days)
            p.save()
    return user, password


def decide_payment(payment_id: int, approve: bool, by: str) -> Payment | None:
    """Approve (premium += the paid days) or reject a pending payment. None = no such payment."""
    with transaction.atomic():
        pay = Payment.objects.select_for_update().select_related("user").filter(pk=payment_id).first()
        if pay is None:
            return None
        if pay.status != Payment.PENDING:
            return pay
        pay.status = Payment.APPROVED if approve else Payment.REJECTED
        pay.decided_by = by[:120]
        pay.decided = timezone.now()
        pay.save()
        if approve:
            p = profile_of(pay.user)
            p.add_premium(pay.days)
            p.save(update_fields=["premium_until"])
    return pay


def stats() -> dict:
    """Everything the admin panel and the bot's /admin show."""
    d = today()
    now = timezone.now()
    day_start = timezone.datetime(d.year, d.month, d.day, tzinfo=TZ)
    week_from = d - timedelta(days=6)
    profiles = Profile.objects.all()
    per_visitor = Visit.objects.values("vid").annotate(n=Count("id"))
    plays_by_game = list(Play.objects.values("slug").annotate(n=Count("id"), people=Count("vid", distinct=True)).order_by("-n"))
    plays_today = {r["slug"]: r["n"] for r in Play.objects.filter(day=d).values("slug").annotate(n=Count("id"))}
    days = []
    for i in range(6, -1, -1):
        day = d - timedelta(days=i)
        days.append(
            {
                "day": day.isoformat(),
                "people": Visit.objects.filter(day=day).values("vid").distinct().count(),
                "visits": Visit.objects.filter(day=day).count(),
                "plays": Play.objects.filter(day=day).count(),
                "newUsers": profiles.filter(created__gte=day_start - timedelta(days=i), created__lt=day_start - timedelta(days=i - 1)).count(),
            }
        )
    return {
        "date": d.isoformat(),
        "users": {
            "total": profiles.count(),
            "newToday": profiles.filter(created__gte=day_start).count(),
            "activeToday": Device.objects.filter(last_seen__gte=day_start).values("user").distinct().count(),
            "premium": profiles.filter(Q(premium_until__gt=now) | Q(role=ROLE_ADMIN)).count(),
            "bogcha": profiles.filter(role=ROLE_BOGCHA).count(),
            "admins": profiles.filter(role=ROLE_ADMIN).count(),
            "telegram": profiles.filter(telegram_id__isnull=False).count(),
            "botActive": profiles.filter(bot_active=True).count(),
        },
        "visits": {
            "people": Visit.objects.values("vid").distinct().count(),
            "total": Visit.objects.count(),
            "peopleToday": Visit.objects.filter(day=d).values("vid").distinct().count(),
            "today": Visit.objects.filter(day=d).count(),
            "peopleWeek": Visit.objects.filter(day__gte=week_from).values("vid").distinct().count(),
            "once": sum(1 for r in per_visitor if r["n"] == 1),
            "twice": sum(1 for r in per_visitor if r["n"] == 2),
            "threePlus": sum(1 for r in per_visitor if r["n"] >= 3),
        },
        "plays": {
            "total": Play.objects.count(),
            "today": Play.objects.filter(day=d).count(),
            "players": Play.objects.values("vid").distinct().count(),
            "playersToday": Play.objects.filter(day=d).values("vid").distinct().count(),
            "games": [
                {"slug": r["slug"], "title": GAME_TITLES.get(r["slug"], r["slug"]), "plays": r["n"], "people": r["people"], "today": plays_today.get(r["slug"], 0)}
                for r in plays_by_game
            ],
        },
        "payments": {"pending": Payment.objects.filter(status=Payment.PENDING).count()},
        "days": days,
    }


def stats_text() -> str:
    s = stats()
    u, v, p = s["users"], s["visits"], s["plays"]
    lines = [
        "📊 <b>moveandplay.uz — statistika</b>",
        f"🗓 {timezone.localtime(timezone.now(), TZ).strftime('%d.%m.%Y %H:%M')}",
        "",
        "👤 <b>Foydalanuvchilar</b>",
        f"   Jami: {u['total']} (bugun yangi: {u['newToday']})",
        f"   Bugun faol: {u['activeToday']}",
        f"   Premium: {u['premium']} · Bog‘cha: {u['bogcha']} · Admin: {u['admins']}",
        f"   Botda: {u['botActive']}",
        "",
        "🌐 <b>Saytga kirishlar</b>",
        f"   Jami: {v['people']} kishi, {v['total']} marta",
        f"   Bugun: {v['peopleToday']} kishi, {v['today']} marta",
        f"   7 kun: {v['peopleWeek']} kishi",
        f"   1 marta: {v['once']} · 2 marta: {v['twice']} · 3+ marta: {v['threePlus']}",
        "",
        f"🎮 <b>O‘yinlar</b>: jami {p['total']} marta ({p['players']} kishi), bugun {p['today']} marta ({p['playersToday']} kishi)",
    ]
    for i, g in enumerate(p["games"], 1):
        lines.append(f"   {i}. {g['title']} — {g['plays']} marta, {g['people']} kishi (bugun {g['today']})")
    if not p["games"]:
        lines.append("   hali hech kim o‘ynamadi")
    if s["payments"]["pending"]:
        lines += ["", f"🧾 Tasdiq kutayotgan to‘lovlar: {s['payments']['pending']}"]
    return "\n".join(lines)
