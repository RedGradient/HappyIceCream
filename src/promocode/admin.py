from django.contrib import admin, messages
from django.contrib.admin.options import ModelAdmin
from django.shortcuts import redirect
from django.urls import path
from django.views.decorators.http import require_POST

from auth.models import User
from promocode.exceptions import NoWinnerFound
from promocode.models import Promocode, UserPromocode
from promocode.services import WinnerService


@admin.register(Promocode)
class PromoCodeAdmin(ModelAdmin):
    list_display = ("id", "code", "is_taken", "is_drawn", "created_at")
    list_filter = ("is_taken", "is_drawn")
    search_fields = ("code",)
    ordering = ("-id",)
    readonly_fields = ("created_at",)


@admin.register(UserPromocode)
class UserPromocodeAdmin(ModelAdmin):
    list_display = ("id", "user", "promocode", "is_won", "won_on", "created_at")
    list_filter = ("is_won", "won_on")
    search_fields = ("user__username", "user__email", "promocode__code")
    ordering = ("-id",)
    readonly_fields = ("created_at",)
    raw_id_fields = ("user", "promocode")


@require_POST
def pick_random_winner_view(request):
    try:
        winner = WinnerService().get_random_winner()
        user = User.objects.filter(pk=winner.user_id).first()
        name = user.get_full_name() or user.username if user else winner.user_id
        messages.success(
            request,
            f"Победитель выбран: {name} (promocode_id={winner.promocode_id}, дата={winner.won_on}).",
        )
    except NoWinnerFound:
        messages.error(
            request, "Не удалось выбрать победителя: нет подходящих кандидатов."
        )
    except Exception as exc:
        messages.error(request, f"Ошибка при выборе победителя: {exc}")

    return redirect("admin:index")


_original_get_urls = admin.site.get_urls


def _get_urls():
    custom_urls = [
        path(
            "pick-random-winner/",
            admin.site.admin_view(pick_random_winner_view),
            name="pick_random_winner",
        ),
    ]
    return custom_urls + _original_get_urls()


admin.site.get_urls = _get_urls
