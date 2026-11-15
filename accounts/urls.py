from django.urls import path

from . import bot_api, views

urlpatterns = [
    path("config", views.config),
    path("auth/register", views.register),
    path("auth/login", views.login),
    path("auth/telegram", views.telegram),
    path("auth/logout", views.logout),
    path("me", views.whoami),
    # admin panel
    path("admin/stats", views.admin_stats),
    path("admin/users", views.admin_users),
    path("admin/users/<int:user_id>", views.admin_user),
    path("admin/bogcha", views.admin_bogcha),
    path("admin/settings", views.admin_settings),
    path("admin/payments", views.admin_payments),
    path("admin/payments/<int:payment_id>", views.admin_payment),
    # Telegram bot (X-Bot-Key)
    path("bot/start", bot_api.start),
    path("bot/credentials", bot_api.credentials),
    path("bot/account", bot_api.account),
    path("bot/config", bot_api.config),
    path("bot/payment", bot_api.payment),
    path("bot/payment/<int:payment_id>", bot_api.payment_decide),
    path("bot/admins", bot_api.admins),
    path("bot/recipients", bot_api.recipients),
    path("bot/blocked", bot_api.blocked),
    path("bot/stats", bot_api.bot_stats),
]
