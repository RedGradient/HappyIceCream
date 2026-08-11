from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from auth.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "id",
        "username",
        "email",
        "first_name",
        "last_name",
        "middle_name",
        "email_confirmed",
        "created_at",
    )
    list_filter = ("email_confirmed", "is_staff", "is_active", "is_superuser")
    search_fields = ("username", "email", "first_name", "last_name", "middle_name")
    ordering = ("-id",)
    readonly_fields = ("created_at", "last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Personal info",
            {"fields": ("first_name", "last_name", "middle_name", "email")},
        ),
        (
            "Status",
            {
                "fields": (
                    "email_confirmed",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined", "created_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "password1", "password2"),
            },
        ),
    )
