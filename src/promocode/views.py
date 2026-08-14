from datetime import datetime, timedelta
from typing import ClassVar

from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from promocode.exceptions import (
    PromocodeAlreadyUsed,
    PromocodeDoesNotExist,
    UserProfileIncomplete,
)
from promocode.serializers import PromoCodeSerializer
from promocode.services import PromoCodeService, WinnerService

MAX_PROMO_ATTEMPTS = 3
COOLDOWN_MINUTES = 5
SESSION_FAILED_ATTEMPTS = "failed_promo_attempts"
SESSION_COOLDOWN_UNTIL = "promo_cooldown_until"


def landing(request):
    winner_days = WinnerService().winners_by_day(7)
    return render(request, "landing.html", {"winner_days": winner_days})


@ensure_csrf_cookie
def account(request):
    if not request.user.is_authenticated:
        return redirect("login")

    user_promocodes = PromoCodeService().user_promocodes_list(request.user)

    return render(
        request,
        "account.html",
        {"user_promocodes": user_promocodes},
    )


def _cooldown_until(request) -> datetime | None:
    raw = request.session.get(SESSION_COOLDOWN_UNTIL)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        request.session.pop(SESSION_COOLDOWN_UNTIL, None)
        return None


def _cooldown_response(request):
    cooldown_until = _cooldown_until(request)
    if cooldown_until is None:
        return None

    now = timezone.now()
    if cooldown_until > now:
        remaining = cooldown_until - now
        minutes, seconds = divmod(int(remaining.total_seconds()), 60)
        return Response(
            {
                "detail": (
                    f"Слишком много попыток. Повторите через {minutes} мин {seconds} сек"
                )
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    _clear_promo_guards(request)
    return None


def _register_failed_attempt(request):
    attempts = request.session.get(SESSION_FAILED_ATTEMPTS, 0) + 1
    request.session[SESSION_FAILED_ATTEMPTS] = attempts

    if attempts >= MAX_PROMO_ATTEMPTS:
        cooldown_until = timezone.now() + timedelta(minutes=COOLDOWN_MINUTES)
        request.session[SESSION_COOLDOWN_UNTIL] = cooldown_until.isoformat()
        request.session[SESSION_FAILED_ATTEMPTS] = 0


def _clear_promo_guards(request):
    request.session.pop(SESSION_FAILED_ATTEMPTS, None)
    request.session.pop(SESSION_COOLDOWN_UNTIL, None)


class PromocodeView(APIView):
    authentication_classes: ClassVar[list] = [SessionAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]

    def get(self, request):
        promos = PromoCodeService().user_promocodes_list(request.user)
        return Response(promos)

    def post(self, request):
        if locked_response := _cooldown_response(request):
            return locked_response

        code_serializer = PromoCodeSerializer(data=request.data)
        code_serializer.is_valid(raise_exception=True)

        user = request.user
        # Для отправки промокода у пользователя должен быть подтвержденный email
        if not user.email_confirmed:
            return Response(
                {"detail": "Для отправки промокода необходимо подтвердить email"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not (user.first_name and user.last_name):
            return Response(
                {"detail": "Для отправки промокода необходимо указать фамилию и имя"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not (user.birth_date and user.telephone_number):
            return Response(
                {
                    "detail": (
                        "Для отправки промокода необходимо указать "
                        "дату рождения и телефон"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            code = code_serializer.validated_data["code"]
            PromoCodeService().apply(code, request.user.id)
        except PromocodeDoesNotExist:
            _register_failed_attempt(request)
            return Response(
                {"detail": "Промокод не найден"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PromocodeAlreadyUsed:
            _register_failed_attempt(request)
            return Response(
                {"detail": "Промокод уже использован"},
                status=status.HTTP_409_CONFLICT,
            )
        except UserProfileIncomplete:
            return Response(
                {
                    "detail": (
                        "Для отправки промокода необходимо указать "
                        "дату рождения и телефон"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        _clear_promo_guards(request)
        return Response({"ok": True})
