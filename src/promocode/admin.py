from django.contrib import admin
from django.contrib.admin.options import ModelAdmin

from promocode.models import PromoCode


@admin.register(PromoCode)
class PromoCodeAdmin(ModelAdmin):
    pass
