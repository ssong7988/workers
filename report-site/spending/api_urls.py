from django.urls import path

from . import api


app_name = "spending-api"

urlpatterns = [
    path("health/", api.health, name="health"),
    path("statements/", api.statements, name="statements"),
]
