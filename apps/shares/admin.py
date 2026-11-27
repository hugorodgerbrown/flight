"""Admin for share links. The token is the link's secret, so the list doesn't show it."""

from django.contrib import admin

from apps.shares.models import Share


@admin.register(Share)
class ShareAdmin(admin.ModelAdmin):
    """Share links, newest first."""

    list_display = ("to_string", "user", "landed_at", "expires_at", "created_at")
    search_fields = ("flight", "fr24_id")
    raw_id_fields = ("user",)
    readonly_fields = ("token", "fr24_id", "snapshot")
