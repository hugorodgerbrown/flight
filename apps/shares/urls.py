"""URLs for share links: the public page under /f/, and making and stopping links in the app."""

from django.urls import path

from apps.shares import views

app_name = "shares"

urlpatterns = [
    path("f/<str:token>/", views.page, name="page"),
    path("f/<str:token>/live.json", views.feed, name="feed"),
    path("f/<str:token>/preview.png", views.preview_png, name="preview"),
    path("app/shares/", views.create, name="create"),
    path("app/shares/<uuid:uuid>/stop/", views.stop, name="stop"),
]
