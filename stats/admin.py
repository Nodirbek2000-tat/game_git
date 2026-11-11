from django.contrib import admin

from .models import Play, Visit


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ("vid", "day", "at")
    list_filter = ("day",)


@admin.register(Play)
class PlayAdmin(admin.ModelAdmin):
    list_display = ("slug", "vid", "day", "at")
    list_filter = ("day", "slug")
