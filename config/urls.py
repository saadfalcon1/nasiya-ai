from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

from shop import api

urlpatterns = [
    path("", RedirectView.as_view(url="/app/", permanent=False)),
    path("admin/", admin.site.urls),
    path("app/", api.app_page, name="app"),
    path("api/me", api.me),
    path("api/dashboard", api.dashboard),
    path("api/debtors", api.debtors),
    path("api/customers/<int:pk>", api.customer_detail),
    path("api/customers/<int:pk>/remind", api.customer_remind),
    path("api/stock", api.stock),
    path("api/transactions", api.transactions),
    path("api/my", api.my_statement),
    path("api/my/tx/<int:pk>", api.my_review),
]
