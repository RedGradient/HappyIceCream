from datetime import datetime, timedelta

from django.shortcuts import render
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from promocode.exceptions import PromocodeAlreadyUsed, PromocodeDoesNotExists
from promocode.serializers import PromoCodeSerializer
from promocode.services import PromoCodeService, WinnerService

MAX_PROMO_ATTEMPTS = 3
COOLDOWN_MINUTES = 5
SESSION_FAILED_ATTEMPTS = "failed_promo_attempts"
SESSION_COOLDOWN_UNTIL = "promo_cooldown_until"


def landing(request):
    winner_limit = 15
    winners = WinnerService().winner_landing_list(winner_limit)

    return render(request, "landing.html", {"winners": winners})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def apply_promocode(request):
    if locked_response := _cooldown_response(request):
        return locked_response

    code_serializer = PromoCodeSerializer(data=request.data)
    code_serializer.is_valid(raise_exception=True)

    user = request.user
    if not (user.first_name and user.last_name):
        return Response(
            {"detail": "Для отправки промокода необходимо указать фамилию и имя"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        code = code_serializer.validated_data["code"]
        PromoCodeService().apply(code, request.user.id)
    except PromocodeDoesNotExists:
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

    _clear_promo_guards(request)
    return Response({"ok": True})


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
