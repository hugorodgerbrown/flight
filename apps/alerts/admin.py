"""Admin for followed flights and push subscriptions."""

from django.contrib import admin

from apps.alerts.models import Follow, PushSubscription


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    """Follows, newest first, with where each alert has got to."""

    list_display = (
        "to_string",
        "user",
        "state",
        "took_off_at",
        "landed_at",
        "took_off_sent_at",
        "landed_sent_at",
        "created_at",
    )
    list_filter = ("push", "email")
    search_fields = ("flight", "fr24_id")
    raw_id_fields = ("user",)


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    """Browsers that get notifications; the keys aren't shown in the list."""

    list_display = ("to_string", "user", "last_sent_at", "created_at")
    raw_id_fields = ("user",)
    readonly_fields = ("endpoint", "p256dh", "auth")
