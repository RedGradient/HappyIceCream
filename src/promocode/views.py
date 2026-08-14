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
from promocode.models import PromoAttempt, PromoAttemptReason
from promocode.serializers import PromoCodeSerializer
from promocode.services import CabinetService, PromoCodeService, WinnerService

MAX_PROMO_ATTEMPTS = 3
ATTEMPT_WINDOW_SECONDS = 60
COOLDOWN_MINUTES = 5
SESSION_FAILED_ATTEMPTS = "failed_promo_attempt_times"
SESSION_COOLDOWN_UNTIL = "promo_cooldown_until"
USER_AGENT_MAX_LENGTH = 512


def _client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def _client_user_agent(request) -> str:
    return (request.META.get("HTTP_USER_AGENT") or "")[:USER_AGENT_MAX_LENGTH]


def _log_failed_promo_attempt(request, *, code: str, reason: str) -> None:
    PromoAttempt.objects.create(
        user=request.user,
        attempted_code=code,
        reason=reason,
        ip_address=_client_ip(request),
        user_agent=_client_user_agent(request),
    )


def landing(request):
    winner_days = WinnerService().winners_by_day(7)
    return render(request, "landing.html", {"winner_days": winner_days})


@ensure_csrf_cookie
def account(request):
    if not request.user.is_authenticated:
        return redirect("login")

    user_promocodes = PromoCodeService().user_promocodes_list(request.user)
    cabinet = CabinetService().summary(request.user)

    return render(
        request,
        "account.html",
        {
            "user_promocodes": user_promocodes,
            "cabinet": cabinet,
        },
    )


def _parse_session_datetime(raw: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _cooldown_until(request) -> datetime | None:
    raw = request.session.get(SESSION_COOLDOWN_UNTIL)
    if not raw:
        return None
    value = _parse_session_datetime(raw)
    if value is None:
        request.session.pop(SESSION_COOLDOWN_UNTIL, None)
    return value


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


def _recent_failed_attempts(request, *, now: datetime) -> list[datetime]:
    window_start = now - timedelta(seconds=ATTEMPT_WINDOW_SECONDS)
    recent: list[datetime] = []
    for raw in request.session.get(SESSION_FAILED_ATTEMPTS, []):
        value = _parse_session_datetime(raw) if isinstance(raw, str) else None
        if value is not None and value >= window_start:
            recent.append(value)
    return recent


def _register_failed_attempt(request):
    now = timezone.now()
    recent = _recent_failed_attempts(request, now=now)
    recent.append(now)
    request.session[SESSION_FAILED_ATTEMPTS] = [item.isoformat() for item in recent]

    if len(recent) >= MAX_PROMO_ATTEMPTS:
        cooldown_until = now + timedelta(minutes=COOLDOWN_MINUTES)
        request.session[SESSION_COOLDOWN_UNTIL] = cooldown_until.isoformat()
        request.session[SESSION_FAILED_ATTEMPTS] = []


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
            _log_failed_promo_attempt(
                request,
                code=code,
                reason=PromoAttemptReason.NOT_FOUND,
            )
            _register_failed_attempt(request)
            return Response(
                {"detail": "Неверный промокод"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PromocodeAlreadyUsed:
            _log_failed_promo_attempt(
                request,
                code=code,
                reason=PromoAttemptReason.ALREADY_USED,
            )
            _register_failed_attempt(request)
            return Response(
                {"detail": "Неверный промокод"},
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


class CabinetView(APIView):
    """GET /api/cabinet/ — участие и чеклист профиля."""

    authentication_classes: ClassVar[list] = [SessionAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]

    def get(self, request):
        return Response(CabinetService().summary(request.user))
