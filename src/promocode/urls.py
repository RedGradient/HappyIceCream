from django.urls import path

from promocode.views import PromocodeView, account, landing

urlpatterns = [
    path("", landing, name="landing"),
    path("account/", account, name="account"),
    path("promocode", PromocodeView.as_view(), name="promocode"),
]
