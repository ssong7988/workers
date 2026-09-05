from django.urls import path

from . import api


app_name = "stock-api"

urlpatterns = [
    path("import-runs/", api.import_runs, name="import-runs"),
    path("status/", api.status, name="status"),
]
