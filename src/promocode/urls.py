from django.urls import path

from promocode.views import CabinetView, PromocodeView, account, landing

urlpatterns = [
    path("", landing, name="landing"),
    path("account/", account, name="account"),
    path("promocode", PromocodeView.as_view(), name="promocode"),
    path("api/cabinet/", CabinetView.as_view(), name="api_cabinet"),
]
