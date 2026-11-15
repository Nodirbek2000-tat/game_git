from django.contrib import admin

from .models import Device, Payment, Profile, SiteSettings


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "role", "telegram_username", "premium_until", "bot_active", "created")
    list_filter = ("role", "bot_active")
    search_fields = ("user__username", "name", "telegram_username")


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "created", "last_seen")
    exclude = ("key",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "days", "status", "created", "decided_by")
    list_filter = ("status",)


admin.site.register(SiteSettings)
