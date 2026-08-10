from django.contrib import admin
from django.contrib.admin.options import ModelAdmin

from auth.models import User


@admin.register(User)
class UserAdmin(ModelAdmin):
    pass
