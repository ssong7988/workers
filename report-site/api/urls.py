from django.urls import path

from . import views


app_name = "api"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("conditions/", views.conditions, name="conditions"),
    path("scans/", views.scans, name="scans"),
    path("digest/", views.digest, name="digest"),
]
