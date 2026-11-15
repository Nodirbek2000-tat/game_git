import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from accounts.models import ROLE_ADMIN, ROLE_BOGCHA, Device, LoginCode, Payment, Profile, SiteSettings
from accounts.services import create_bogcha
from stats.models import Play, Visit

pytestmark = pytest.mark.django_db
User = get_user_model()
KEY = "test-bot-key"


@pytest.fixture(autouse=True)
def _settings(settings):
    from django.core.cache import cache

    cache.clear()
    settings.BOT_API_KEY = KEY
    settings.ADMIN_TELEGRAM_IDS = [777]
    settings.BOT_USERNAME = "moveandplay_bot"


def call(client, method, url, data=None, token=None, bot=False):
    h = {}
    if token:
        h["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    if bot:
        h["HTTP_X_BOT_KEY"] = KEY
    if method == "get":
        r = client.get(url, data or {}, secure=True, **h)
    else:
        r = client.post(url, json.dumps(data or {}), content_type="application/json", secure=True, **h)
    return r.status_code, (r.json() if r.content and r["Content-Type"].startswith("application/json") else None)


def register(c, username="ali", password="secret12"):
    return call(c, "post", "/api/auth/register", {"username": username, "password": password, "name": "Ali"})


# ------------------------------------------------------------------------------------------- password sign-in


def test_register_login_me_logout():
    c = Client()
    s, d = register(c)
    assert s == 200 and d["token"] and d["me"]["username"] == "ali" and d["me"]["premium"] is False
    s, d2 = call(c, "get", "/api/me", token=d["token"])
    assert s == 200 and d2["me"]["name"] == "Ali"
    s, d3 = call(c, "post", "/api/auth/login", {"username": "ALI", "password": "secret12"})
    assert s == 200
    assert call(c, "post", "/api/auth/logout", token=d3["token"])[0] == 200
    assert call(c, "get", "/api/me", token=d3["token"])[0] == 401
    assert call(c, "get", "/api/me", token=d["token"])[0] == 200  # the other device is still signed in


@pytest.mark.parametrize("body,status", [({"username": "a", "password": "secret12"}, 400), ({"username": "bob", "password": "123"}, 400)])
def test_register_validation(body, status):
    assert call(Client(), "post", "/api/auth/register", body)[0] == status


def test_register_taken_and_wrong_password_and_lockout():
    c = Client()
    register(c)
    assert register(c, "Ali")[0] == 409
    for _ in range(8):
        assert call(c, "post", "/api/auth/login", {"username": "ali", "password": "wrong"})[0] == 401
    assert call(c, "post", "/api/auth/login", {"username": "ali", "password": "secret12"})[0] == 429


def test_tokens_are_stored_hashed():
    c = Client()
    _, d = register(c)
    assert not Device.objects.filter(key=d["token"]).exists()
    assert Device.objects.count() == 1


# ------------------------------------------------------------------------------------------- device limits


def test_ordinary_account_drops_its_oldest_device():
    c = Client()
    _, first = register(c)
    tokens = [call(c, "post", "/api/auth/login", {"username": "ali", "password": "secret12"})[1]["token"] for _ in range(3)]
    assert Device.objects.count() == 3
    assert call(c, "get", "/api/me", token=first["token"])[0] == 401
    assert call(c, "get", "/api/me", token=tokens[-1])[0] == 200


def test_kindergarten_account_allows_10_devices_then_refuses():
    user, password = create_bogcha("Quyoshcha bog‘chasi", days=30)
    c = Client()
    for _ in range(10):
        assert call(c, "post", "/api/auth/login", {"username": user.username, "password": password})[0] == 200
    s, d = call(c, "post", "/api/auth/login", {"username": user.username, "password": password})
    assert s == 409 and "10 ta qurilma" in d["error"]
    assert Profile.objects.get(user=user).is_premium


# ------------------------------------------------------------------------------------------- Telegram sign-in + bot API


def test_bot_api_needs_the_key():
    assert call(Client(), "post", "/api/bot/start", {"tg_id": 5})[0] == 403


def test_telegram_login_flow():
    c = Client()
    s, d = call(c, "post", "/api/auth/telegram")
    code = d["code"]
    assert d["url"] == f"https://t.me/moveandplay_bot?start=login_{code}"
    assert call(c, "get", "/api/auth/telegram", {"code": code})[0] == 202
    s, b = call(c, "post", "/api/bot/start", {"tg_id": 1001, "first_name": "Vali", "username": "vali", "payload": f"login_{code}"}, bot=True)
    assert s == 200 and b["login"] == "ok" and b["created"] is True
    s, d2 = call(c, "get", "/api/auth/telegram", {"code": code})
    assert s == 200 and d2["me"]["telegram"] is True and d2["me"]["name"] == "Vali"
    # the code works only once
    assert call(c, "get", "/api/auth/telegram", {"code": code})[0] == 410
    # /start again: same account
    call(c, "post", "/api/bot/start", {"tg_id": 1001, "username": "vali"}, bot=True)
    assert Profile.objects.filter(telegram_id=1001).count() == 1


def test_expired_login_code():
    lc = LoginCode.objects.create(code="old")
    LoginCode.objects.filter(pk=lc.pk).update(created=timezone.now() - timedelta(minutes=11))
    s, b = call(Client(), "post", "/api/bot/start", {"tg_id": 5, "payload": "login_old"}, bot=True)
    assert b["login"] == "expired"


def test_listed_telegram_id_becomes_admin():
    s, b = call(Client(), "post", "/api/bot/start", {"tg_id": 777}, bot=True)
    assert b["isAdmin"] is True and Profile.objects.get(telegram_id=777).role == ROLE_ADMIN


def test_bot_gives_login_and_password_that_work_on_the_site():
    c = Client()
    call(c, "post", "/api/bot/start", {"tg_id": 42, "username": "olim"}, bot=True)
    s, cr = call(c, "post", "/api/bot/credentials", {"tg_id": 42}, bot=True)
    assert s == 200 and cr["username"] == "olim" and len(cr["password"]) == 8
    assert call(c, "post", "/api/auth/login", {"username": cr["username"], "password": cr["password"]})[0] == 200


# ------------------------------------------------------------------------------------------- premium payments


def test_payment_approved_by_admin_gives_30_days():
    c = Client()
    SiteSettings.objects.update_or_create(id=1, defaults={"monthly_price": 30000, "card_number": "8600 0000 0000 0000"})
    call(c, "post", "/api/bot/start", {"tg_id": 10}, bot=True)
    call(c, "post", "/api/bot/start", {"tg_id": 777}, bot=True)
    s, p = call(c, "post", "/api/bot/payment", {"tg_id": 10, "file_id": "PHOTO"}, bot=True)
    assert s == 200 and p["amount"] == 30000
    # not an admin
    assert call(c, "post", f"/api/bot/payment/{p['id']}", {"admin_tg_id": 10, "approve": True}, bot=True)[0] == 403
    s, r = call(c, "post", f"/api/bot/payment/{p['id']}", {"admin_tg_id": 777, "approve": True}, bot=True)
    assert s == 200 and r["status"] == "approved" and r["userTgId"] == 10 and r["already"] is False
    prof = Profile.objects.get(telegram_id=10)
    assert prof.is_premium and prof.premium_until > timezone.now() + timedelta(days=29)
    # a second press does not add again
    s, r2 = call(c, "post", f"/api/bot/payment/{p['id']}", {"admin_tg_id": 777, "approve": True}, bot=True)
    assert r2["already"] is True
    assert Profile.objects.get(telegram_id=10).premium_until == prof.premium_until


def test_rejected_payment_and_pending_limit():
    c = Client()
    call(c, "post", "/api/bot/start", {"tg_id": 11}, bot=True)
    ids = [call(c, "post", "/api/bot/payment", {"tg_id": 11, "file_id": f"P{i}"}, bot=True)[1]["id"] for i in range(3)]
    assert call(c, "post", "/api/bot/payment", {"tg_id": 11, "file_id": "P4"}, bot=True)[0] == 429
    call(c, "post", "/api/bot/start", {"tg_id": 777}, bot=True)
    s, r = call(c, "post", f"/api/bot/payment/{ids[0]}", {"admin_tg_id": 777, "approve": False}, bot=True)
    assert r["status"] == "rejected" and not Profile.objects.get(telegram_id=11).is_premium


# ------------------------------------------------------------------------------------------- admin panel


def admin_token(c):
    register(c, "boss", "secret12")
    Profile.objects.filter(user__username="boss").update(role=ROLE_ADMIN)
    return call(c, "post", "/api/auth/login", {"username": "boss", "password": "secret12"})[1]["token"]


def test_admin_endpoints_need_an_admin():
    c = Client()
    _, d = register(c)
    for url in ("/api/admin/stats", "/api/admin/users", "/api/admin/settings", "/api/admin/payments"):
        assert call(c, "get", url, token=d["token"])[0] == 403
        assert call(c, "get", url)[0] == 401


def test_admin_manages_users_kindergartens_settings_and_sees_stats():
    c = Client()
    tok = admin_token(c)
    _, u = register(c, "user1")
    uid = u["me"]["id"]
    s, r = call(c, "post", f"/api/admin/users/{uid}", {"role": "admin", "premiumDays": 30, "newPassword": True}, token=tok)
    assert s == 200 and r["user"]["isAdmin"] and r["user"]["premium"] and len(r["password"]) == 8
    s, b = call(c, "post", "/api/admin/bogcha", {"name": "Lola bog‘chasi", "username": "lola_bogcha", "premiumDays": 365}, token=tok)
    assert s == 200 and b["username"] == "lola_bogcha" and len(b["password"]) == 10
    assert Profile.objects.get(user__username="lola_bogcha").role == ROLE_BOGCHA
    s, st = call(c, "post", "/api/admin/settings", {"monthlyPrice": 25000, "cardNumber": "8600", "bogchaPhone": "+998 90 000 00 00", "freeGames": ["meva-ninja", "boks"]}, token=tok)
    assert st["monthlyPrice"] == 25000 and st["freeGames"] == ["meva-ninja", "boks"]
    s, cfg = call(c, "get", "/api/config")
    assert cfg["bogchaPhone"] == "+998 90 000 00 00" and cfg["freeGames"] == ["meva-ninja", "boks"]
    s, lst = call(c, "get", "/api/admin/users", {"q": "lola"}, token=tok)
    assert lst["total"] == 1
    Visit.objects.create(vid="a" * 36, day=timezone.localdate())
    Play.objects.create(vid="a" * 36, slug="boks", day=timezone.localdate())
    s, stt = call(c, "get", "/api/admin/stats", token=tok)
    assert s == 200 and stt["users"]["total"] == 3 and stt["plays"]["total"] == 1 and len(stt["days"]) == 7
    # cannot remove own admin role
    me_id = User.objects.get(username="boss").id
    assert call(c, "post", f"/api/admin/users/{me_id}", {"role": "user"}, token=tok)[0] == 400


def test_bot_stats_only_for_admins():
    c = Client()
    call(c, "post", "/api/bot/start", {"tg_id": 777}, bot=True)
    call(c, "post", "/api/bot/start", {"tg_id": 5}, bot=True)
    assert call(c, "get", "/api/bot/stats", {"tg_id": 5}, bot=True)[0] == 403
    s, d = call(c, "get", "/api/bot/stats", {"tg_id": 777}, bot=True)
    assert s == 200 and "Foydalanuvchilar" in d["text"]
    s, a = call(c, "get", "/api/bot/admins", bot=True)
    assert 777 in a["ids"]
    s, r = call(c, "get", "/api/bot/recipients", bot=True)
    assert set(r["ids"]) == {777, 5}
    call(c, "post", "/api/bot/blocked", {"tg_id": 5}, bot=True)
    assert call(c, "get", "/api/bot/recipients", bot=True)[1]["ids"] == [777]


def test_stats_event_links_the_signed_in_user():
    c = Client()
    _, d = register(c)
    r = c.post("/api/stats/event", json.dumps({"vid": "12345678-1234-4123-8123-123456789abc", "type": "play", "slug": "boks"}), content_type="application/json", secure=True, HTTP_AUTHORIZATION=f"Bearer {d['token']}")
    assert r.status_code == 204
    assert Play.objects.get().user.username == "ali"
    assert Payment.objects.count() == 0
