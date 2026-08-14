from typing import Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString

from auth.models import User
from promocode.models import PromoActivation

PROMOCODES_PREVIEW_LIMIT = 20


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "id",
        "username",
        "email",
        "first_name",
        "last_name",
        "middle_name",
        "birth_date",
        "telephone_number",
        "email_confirmed",
        "notify_on_promocode",
        "winner",
        "created_at",
    )
    list_filter = (
        "email_confirmed",
        "notify_on_promocode",
        "winner",
        "is_staff",
        "is_active",
        "is_superuser",
    )
    search_fields = (
        "username",
        "email",
        "first_name",
        "last_name",
        "middle_name",
        "telephone_number",
    )
    ordering = ("-id",)
    readonly_fields = ("created_at", "last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Personal info",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "middle_name",
                    "birth_date",
                    "telephone_number",
                    "email",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "email_confirmed",
                    "notify_on_promocode",
                    "winner",
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

    def get_fieldsets(
        self, request: HttpRequest, obj: User | None = None
    ) -> list[tuple[str | None, dict[str, Any]]]:
        fieldsets = list(super().get_fieldsets(request, obj))
        if obj is not None:
            fieldsets.append(("Промокоды", {"fields": ("promocodes_preview",)}))
        return fieldsets

    def get_readonly_fields(
        self, request: HttpRequest, obj: User | None = None
    ) -> list[str]:
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields.append("promocodes_preview")
        return fields

    @admin.display(description="Последние активации")
    def promocodes_preview(self, obj: User) -> SafeString:
        all_url = (
            reverse("admin:promocode_promoactivation_changelist")
            + f"?user__id__exact={obj.pk}"
        )
        rows = list(
            PromoActivation.objects.filter(user=obj)
            .select_related("promocode")
            .order_by("-created_at")[: PROMOCODES_PREVIEW_LIMIT + 1]
        )
        has_more = len(rows) > PROMOCODES_PREVIEW_LIMIT
        rows = rows[:PROMOCODES_PREVIEW_LIMIT]

        button = format_html(
            '<p style="margin:0.75rem 0 0;"><a class="button" href="{}">Все</a></p>',
            all_url,
        )

        if not rows:
            return format_html(
                '<p style="margin:0;">Промокодов пока нет.</p>{}',
                button,
            )

        table_rows = format_html_join(
            "",
            ("<tr><td>{}</td><td><code>{}</code>{}</td></tr>"),
            (
                (
                    row.created_at.strftime("%d.%m.%Y %H:%M"),
                    row.promocode.code,
                    " · победа" if row.is_won else "",
                )
                for row in rows
            ),
        )
        more = (
            format_html(
                '<p style="margin:0.5rem 0 0;color:#666;font-size:0.85rem;">'
                "Показаны последние {}.</p>",
                PROMOCODES_PREVIEW_LIMIT,
            )
            if has_more
            else ""
        )
        return format_html(
            '<table style="width:100%;max-width:32rem;border-collapse:collapse;">'
            "<thead><tr>"
            '<th style="text-align:left;padding:0.35rem 0.5rem;">Дата</th>'
            '<th style="text-align:left;padding:0.35rem 0.5rem;">Код</th>'
            "</tr></thead>"
            "<tbody>{}</tbody>"
            "</table>"
            "{}{}",
            table_rows,
            more,
            button,
        )
