"""URLs for the installed app's own pages, under /app/."""

from django.urls import path

from apps.flights import views

app_name = "flights"

urlpatterns = [
    path("", views.home, name="home"),
]
