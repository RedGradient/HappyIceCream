from django.urls import path

from promocode.views import apply_promocode, landing

urlpatterns = [
    path("", landing, name="landing"),
    path("promocode", apply_promocode, name="promocode"),
]
