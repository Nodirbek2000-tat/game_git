"""The statistics the Telegram bot sends: who came, how often, which games were played. Days are counted in Tashkent time."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count
from django.utils import timezone

from .models import Play, Visit

TZ = ZoneInfo("Asia/Tashkent")

# slug -> the name shown in the bot (a game missing here is shown by its slug)
GAME_TITLES = {
    "meva-ninja": "Meva Ninja",
    "baliq-ovi": "Baliq ovi",
    "mashina": "Mashina haydash",
    "poyga": "Shahar simulyatori",
    "boks": "Boks",
    "fitnes": "Fitnes",
    "pufakchalar": "Pufakchalar",
    "hayvonlar": "Hayvonlar",
    "baliqcha": "Baliqcha",
    "devor-bolalar": "Devordan o‘tamiz",
    "sanaymiz": "Sanaymiz",
    "arqon": "Arqon sakrash",
    "engash-sakra": "Eng, sakra",
    "darvozabon": "Darvozabon",
    "yulduzcha": "Yulduzcha mashqi",
    "voleybol": "Voleybol",
    "tez-teg": "Tez teg",
    "basketbol": "Basketbol",
    "raqs": "Raqs",
}


def today(now: datetime | None = None) -> date:
    return timezone.localtime(now or timezone.now(), TZ).date()


def build_report(now: datetime | None = None) -> str:
    d = today(now)
    week_from = d - timedelta(days=6)

    visits_total = Visit.objects.count()
    people_total = Visit.objects.values("vid").distinct().count()
    visits_today = Visit.objects.filter(day=d).count()
    people_today = Visit.objects.filter(day=d).values("vid").distinct().count()
    people_week = Visit.objects.filter(day__gte=week_from).values("vid").distinct().count()
    visits_week = Visit.objects.filter(day__gte=week_from).count()

    # how many times every visitor came (all time)
    per = Visit.objects.values("vid").annotate(n=Count("id"))
    once = sum(1 for r in per if r["n"] == 1)
    twice = sum(1 for r in per if r["n"] == 2)
    three_plus = sum(1 for r in per if r["n"] >= 3)
    # first visit today
    earlier = Visit.objects.filter(day__lt=d).values("vid").distinct()
    new_today = Visit.objects.filter(day=d).exclude(vid__in=earlier).values("vid").distinct().count()

    plays_total = Play.objects.count()
    plays_today = Play.objects.filter(day=d).count()
    by_game = {r["slug"]: r["n"] for r in Play.objects.values("slug").annotate(n=Count("id"))}
    by_game_today = {r["slug"]: r["n"] for r in Play.objects.filter(day=d).values("slug").annotate(n=Count("id"))}

    lines = [
        "📊 <b>moveandplay.uz statistikasi</b>",
        f"🗓 {d.strftime('%d.%m.%Y')}",
        "",
        f"👥 <b>Jami:</b> {people_total} kishi, {visits_total} marta kirdi",
        f"📅 <b>Bugun:</b> {people_today} kishi, {visits_today} marta kirdi",
        f"🆕 Bugun birinchi marta kirganlar: {new_today} kishi",
        f"📆 Oxirgi 7 kun: {people_week} kishi, {visits_week} marta",
        "",
        "🔁 <b>Necha marta kirgan:</b>",
        f"   1 marta — {once} kishi",
        f"   2 marta — {twice} kishi",
        f"   3 va undan ko‘p — {three_plus} kishi",
        "",
        f"🎮 <b>O‘yinlar:</b> jami {plays_total} marta, bugun {plays_today} marta",
    ]
    if by_game:
        for i, (slug, n) in enumerate(sorted(by_game.items(), key=lambda kv: -kv[1]), 1):
            lines.append(f"   {i}. {GAME_TITLES.get(slug, slug)} — {n} (bugun {by_game_today.get(slug, 0)})")
    else:
        lines.append("   hali hech kim o‘ynamadi")
    return "\n".join(lines)
