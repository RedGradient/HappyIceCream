from django.urls import path

from promocode.views import PromocodeView, landing

urlpatterns = [
    path("", landing, name="landing"),
    path("promocode", PromocodeView.as_view(), name="promocode"),
]
