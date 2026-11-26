"""URLs for following flights: the app's under /app/alerts/, and the emails' stop link."""

from django.urls import path

from apps.alerts import views

app_name = "alerts"

urlpatterns = [
    path("app/alerts/follow/", views.follow, name="follow"),
    path("app/alerts/<uuid:uuid>/toggle/", views.toggle, name="toggle"),
    path("app/alerts/<uuid:uuid>/stop/", views.stop, name="stop_following"),
    path("app/alerts/push/", views.push_subscribe, name="push_subscribe"),
    path("app/alerts/push/delete/", views.push_unsubscribe, name="push_unsubscribe"),
    path("alerts/stop/<str:token>/", views.email_stop, name="stop"),
]
