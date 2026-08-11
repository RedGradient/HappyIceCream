from django.contrib import admin, messages
from django.contrib.admin.options import ModelAdmin
from django.shortcuts import redirect
from django.urls import path
from django.views.decorators.http import require_POST

from auth.models import User
from promocode.exceptions import NoWinnerFound
from promocode.models import PromoCode, UserPromocode
from promocode.services import WinnerService


@admin.register(PromoCode)
class PromoCodeAdmin(ModelAdmin):
    pass


@admin.register(UserPromocode)
class UserPromocodeAdmin(ModelAdmin):
    pass


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
