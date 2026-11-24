from django.contrib import admin
from django.http import HttpRequest, JsonResponse
from django.urls import include, path

admin.site.site_header = "PriceWatch"
admin.site.site_title = "PriceWatch"
admin.site.index_title = "Tracked products"


def healthcheck(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", include("apps.dashboard.urls")),
    path("api/", include("apps.api.urls")),
    path("admin/", admin.site.urls),
    path("healthz/", healthcheck, name="healthcheck"),
]
