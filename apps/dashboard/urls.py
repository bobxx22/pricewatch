from django.urls import path

from apps.dashboard.views import ExportView, ProductDetailView, ProductListView

app_name = "dashboard"

urlpatterns = [
    path("", ProductListView.as_view(), name="index"),
    path("products/<int:pk>/", ProductDetailView.as_view(), name="product"),
    path("export/products.<str:fmt>", ExportView.as_view(), name="export"),
]
