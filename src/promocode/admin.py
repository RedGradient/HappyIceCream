from django.contrib import admin
from django.contrib.admin.options import ModelAdmin

from promocode.models import PromoCode, UserPromocode


@admin.register(PromoCode)
class PromoCodeAdmin(ModelAdmin):
    pass


@admin.register(UserPromocode)
class UserPromocodeAdmin(ModelAdmin):
    pass
