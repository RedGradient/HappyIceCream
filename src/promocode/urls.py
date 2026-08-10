from django.urls import path

from promocode.views import landing, promo

urlpatterns = [
    path("", landing, name="landing"),
    path("promocode", promo, name="promocode"),
]
