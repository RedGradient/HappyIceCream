import io
import logging
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from django.db.models import Count, Q
from django.utils import timezone

from auth.models import User
from promocode.models import (
    DailyDraw,
    Prize,
    PromoActivation,
    PromoAttempt,
    PromoAttemptReason,
    Promocode,
)
from promocode.services.winner import WINNERS_PER_DAY, WinnerService

logger = logging.getLogger(__name__)


class AnalyticsService:
    @staticmethod
    def summary() -> dict[str, Any]:
        """Сводные метрики для админки."""

        today = timezone.localdate()
        week_ago = timezone.now() - timedelta(days=7)
        pool = WinnerService.current_pool_summary()

        users_profile_complete = (
            User.objects.filter(
                email_confirmed=True,
                birth_date__isnull=False,
            )
            .exclude(first_name="")
            .exclude(last_name="")
            .exclude(telephone_number__isnull=True)
            .exclude(telephone_number="")
            .count()
        )

        attempts_today = PromoAttempt.objects.filter(created_at__date=today)
        attempts_week = PromoAttempt.objects.filter(created_at__gte=week_ago)

        draw_days_incomplete = (
            DailyDraw.objects.values("date")
            .annotate(winners=Count("id", filter=Q(user__isnull=False)))
            .filter(winners__lt=WINNERS_PER_DAY)
            .count()
        )

        return {
            "users_total": User.objects.count(),
            "users_email_confirmed": User.objects.filter(email_confirmed=True).count(),
            "users_profile_complete": users_profile_complete,
            "unique_participants": (
                User.objects.filter(user_promocodes__isnull=False).distinct().count()
            ),
            "users_winners": User.objects.filter(winner=True).count(),
            "activations_total": PromoActivation.objects.count(),
            "activations_today": PromoActivation.objects.filter(
                created_at__date=today
            ).count(),
            "activations_7d": PromoActivation.objects.filter(
                created_at__gte=week_ago
            ).count(),
            "free_promocodes": Promocode.objects.filter(is_taken=False).count(),
            "pool_activations": pool["count"],
            "pool_unique_users": pool["unique_users"],
            "pool_activated_from": pool["activated_from"],
            "next_draw_at": pool["next_draw_at"],
            "winners_total": DailyDraw.objects.filter(user__isnull=False).count(),
            "winners_today": DailyDraw.objects.filter(
                date=today, user__isnull=False
            ).count(),
            "winners_airpods": DailyDraw.objects.filter(
                user__isnull=False, prize=Prize.AIRPODS
            ).count(),
            "winners_ozon": DailyDraw.objects.filter(
                user__isnull=False, prize=Prize.OZON_COUPON
            ).count(),
            "days_without_full_draw": draw_days_incomplete,
            "attempts_today": attempts_today.count(),
            "attempts_7d": attempts_week.count(),
            "attempts_today_not_found": attempts_today.filter(
                reason=PromoAttemptReason.NOT_FOUND
            ).count(),
            "attempts_today_already_used": attempts_today.filter(
                reason=PromoAttemptReason.ALREADY_USED
            ).count(),
            "attempts_7d_not_found": attempts_week.filter(
                reason=PromoAttemptReason.NOT_FOUND
            ).count(),
            "attempts_7d_already_used": attempts_week.filter(
                reason=PromoAttemptReason.ALREADY_USED
            ).count(),
        }

    @staticmethod
    def export_analytics_as_excel() -> tuple[bytes, str]:
        metrics = AnalyticsService.summary()
        labels = {
            "users_total": "Зарегистрировались",
            "users_email_confirmed": "Подтвердили email",
            "users_profile_complete": ("Заполнили ФИО, телефон, дату рождения и email"),
            "unique_participants": "Ввели хотя бы один промокод",
            "users_winners": "Уже выиграли (больше не участвуют)",
            "activations_total": "Промокодов активировано всего",
            "activations_today": "Промокодов активировано сегодня",
            "activations_7d": "Промокодов активировано за 7 дней",
            "free_promocodes": "Промокодов ещё не введено",
            "pool_activations": "Промокодов участвует в розыгрыше",
            "pool_unique_users": "Людей участвует в розыгрыше",
            "pool_activated_from": "Учитываются промокоды с",
            "next_draw_at": "Когда следующий розыгрыш",
            "winners_total": "Сколько раз выбрали победителя",
            "winners_today": "Победителей выбрано сегодня",
            "winners_airpods": "Выдали AirPods",
            "winners_ozon": "Выдали купон OZON",
            "days_without_full_draw": ("Дней, когда выбрали меньше 2 победителей"),
            "attempts_today": "Ошибок ввода сегодня",
            "attempts_today_not_found": "Сегодня ввели несуществующий код",
            "attempts_today_already_used": ("Сегодня ввели уже использованный код"),
            "attempts_7d": "Ошибок ввода за 7 дней",
            "attempts_7d_not_found": "За 7 дней: несуществующий код",
            "attempts_7d_already_used": "За 7 дней: уже использованный код",
        }
        rows = []
        for key, label in labels.items():
            value = metrics[key]
            if value is None:
                value = "—"
            elif isinstance(value, datetime):
                value = timezone.localtime(value).strftime("%d.%m.%Y %H:%M")
            elif isinstance(value, date):
                value = value.strftime("%d.%m.%Y")
            rows.append((label, value))

        df = pd.DataFrame(rows, columns=["Показатель", "Значение"])

        buffer = io.BytesIO()
        df.to_excel(buffer, index=False)
        filename = f"metrics-{timezone.localtime().strftime('%Y-%m-%d_%H-%M')}.xlsx"
        return buffer.getvalue(), filename
