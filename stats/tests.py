import json
import uuid
from datetime import datetime, timezone as dt_tz

import pytest
from django.test import Client

from stats.models import Play, Visit
from stats.report import build_report, today

pytestmark = pytest.mark.django_db

URL = "/api/stats/event"


def post(client: Client, body) -> int:
    data = body if isinstance(body, (bytes, str)) else json.dumps(body)
    return client.post(URL, data=data, content_type="application/json", secure=True).status_code


def vid() -> str:
    return str(uuid.uuid4())


def test_visit_and_play_are_stored():
    c = Client()
    v = vid()
    assert post(c, {"vid": v, "type": "visit"}) == 204
    assert post(c, {"vid": v, "type": "play", "slug": "meva-ninja"}) == 204
    assert Visit.objects.filter(vid=v).count() == 1
    assert Play.objects.get(vid=v).slug == "meva-ninja"


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        "[]",
        {"vid": "abc", "type": "visit"},
        {"vid": str(uuid.uuid4()), "type": "hack"},
        {"vid": str(uuid.uuid4()), "type": "play", "slug": "<script>"},
        {"vid": str(uuid.uuid4()), "type": "play"},
    ],
)
def test_bad_events_are_rejected(body):
    assert post(Client(), body) == 400
    assert Visit.objects.count() == 0 and Play.objects.count() == 0


def test_get_is_not_allowed_and_big_bodies_are_refused():
    c = Client()
    assert c.get(URL, secure=True).status_code == 405
    assert post(c, {"vid": vid(), "type": "visit", "pad": "x" * 600}) == 413


def test_one_browser_cannot_flood(settings):
    import stats.views as views

    views.DAY_LIMIT = 5
    try:
        c = Client()
        v = vid()
        for _ in range(12):
            post(c, {"vid": v, "type": "visit"})
        assert Visit.objects.filter(vid=v).count() == 5
    finally:
        views.DAY_LIMIT = 300


def test_report_counts_people_visits_repeaters_and_games():
    d = today()
    a, b, c = vid(), vid(), vid()
    for v, n in ((a, 1), (b, 2), (c, 4)):
        for _ in range(n):
            Visit.objects.create(vid=v, day=d)
    for slug in ("boks", "boks", "fitnes"):
        Play.objects.create(vid=a, slug=slug, day=d)
    text = build_report()
    assert "3 kishi, 7 marta kirdi" in text
    assert "1 marta — 1 kishi" in text
    assert "2 marta — 1 kishi" in text
    assert "3 va undan ko‘p — 1 kishi" in text
    assert "Boks — 2 (bugun 2)" in text
    assert "Fitnes — 1" in text
    assert text.index("Boks") < text.index("Fitnes")


def test_today_is_tashkent_time():
    # 20:30 UTC = 01:30 the next day in Tashkent (UTC+5)
    assert str(today(datetime(2026, 11, 11, 20, 30, tzinfo=dt_tz.utc))) == "2026-11-12"

