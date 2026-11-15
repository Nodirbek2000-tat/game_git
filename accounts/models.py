"""Accounts of moveandplay.uz: a Django user + a profile (role, Telegram, premium, device limit), the devices that are signed in,
the one-time Telegram login codes, premium payments (a receipt checked by an admin) and the site settings the admins edit."""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

ROLE_USER = "user"
ROLE_BOGCHA = "bogcha"
ROLE_ADMIN = "admin"
ROLES = [(ROLE_USER, "Oddiy"), (ROLE_BOGCHA, "Bog‘cha"), (ROLE_ADMIN, "Admin")]

# how many devices may be signed in at once
DEVICE_LIMIT = {ROLE_USER: 3, ROLE_BOGCHA: 10, ROLE_ADMIN: 5}


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=ROLES, default=ROLE_USER, db_index=True)
    name = models.CharField(max_length=120, blank=True)
    telegram_id = models.BigIntegerField(null=True, blank=True, unique=True)
    telegram_username = models.CharField(max_length=64, blank=True)
    premium_until = models.DateTimeField(null=True, blank=True)
    # the user started the bot and did not block it: gets the morning message
    bot_active = models.BooleanField(default=False, db_index=True)
    created = models.DateTimeField(auto_now_add=True)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN or self.user.is_superuser

    @property
    def is_premium(self) -> bool:
        # admins and kindergartens with a valid date; admins always
        if self.is_admin:
            return True
        return self.premium_until is not None and self.premium_until > timezone.now()

    @property
    def device_limit(self) -> int:
        return DEVICE_LIMIT.get(self.role, 3)

    def add_premium(self, days: int) -> None:
        start = self.premium_until if self.premium_until and self.premium_until > timezone.now() else timezone.now()
        self.premium_until = start + timedelta(days=days)

    def display(self) -> str:
        return self.name or (f"@{self.telegram_username}" if self.telegram_username else self.user.username)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class Device(models.Model):
    """A signed-in device. Only the hash of its token is stored: a leaked database does not leak sessions."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices")
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now_add=True, db_index=True)

    @staticmethod
    def issue(user, name: str = "") -> tuple["Device", str]:
        raw = secrets.token_urlsafe(32)
        return Device.objects.create(user=user, key=hash_token(raw), name=name[:120]), raw


class LoginCode(models.Model):
    """"Telegram orqali kirish": the site makes a code, the bot confirms it for its user, the site picks the session up once."""

    code = models.CharField(max_length=40, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)

    TTL = timedelta(minutes=10)

    @property
    def expired(self) -> bool:
        return timezone.now() - self.created > self.TTL


class Payment(models.Model):
    PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
    STATUSES = [(PENDING, "Kutilmoqda"), (APPROVED, "Tasdiqlandi"), (REJECTED, "Rad etildi")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments")
    amount = models.PositiveIntegerField(default=0)
    days = models.PositiveIntegerField(default=30)
    receipt_file_id = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING, db_index=True)
    decided_by = models.CharField(max_length=120, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    decided = models.DateTimeField(null=True, blank=True)


# the games that stay free when the admins have not chosen yet
DEFAULT_FREE_GAMES = ["meva-ninja", "pufakchalar", "fitnes"]


class SiteSettings(models.Model):
    """One row: what the admins set in the panel."""

    monthly_price = models.PositiveIntegerField(default=0)
    card_number = models.CharField(max_length=40, blank=True)
    card_holder = models.CharField(max_length=120, blank=True)
    bogcha_phone = models.CharField(max_length=40, blank=True)
    free_games = models.JSONField(default=list)
    updated = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls) -> "SiteSettings":
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create(free_games=list(DEFAULT_FREE_GAMES))
        return obj
