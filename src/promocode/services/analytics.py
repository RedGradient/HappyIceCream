import io
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any

import pandas as pd
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

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

DAILY_SERIES_DAYS = 30
MAX_METRICS_PERIOD_DAYS = 366

DAILY_SERIES_COLUMNS: dict[str, str] = {
    "date": "Дата",
    "registrations": "Регистрации",
    "activations": "Активации",
    "attempts": "Ошибки ввода",
    "attempts_not_found": "Несуществующий код",
    "attempts_already_used": "Уже использованный код",
    "winners": "Победителей",
    "draw_full": "Полный розыгрыш",
}


class MetricFormat(str, Enum):
    NUMBER = "number"
    DATETIME = "datetime"
    DATE = "date"


@dataclass(frozen=True, slots=True)
class MetricSpec:
    key: str
    label: str
    section: str
    fmt: MetricFormat = MetricFormat.NUMBER


# Единый каталог метрик: UI и Excel берут подписи/секции отсюда.
METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec("users_total", "Зарегистрировались", "Пользователи"),
    MetricSpec("users_email_confirmed", "Подтвердили email", "Пользователи"),
    MetricSpec(
        "users_profile_complete",
        "Заполнили ФИО, телефон, дату рождения и email",
        "Пользователи",
    ),
    MetricSpec(
        "unique_participants",
        "Ввели хотя бы один промокод",
        "Пользователи",
    ),
    MetricSpec(
        "users_winners",
        "Уже выиграли (больше не участвуют)",
        "Пользователи",
    ),
    MetricSpec(
        "activations_total",
        "Промокодов активировано всего",
        "Промокоды",
    ),
    MetricSpec(
        "activations_period",
        "Промокодов активировано за период",
        "Промокоды",
    ),
    MetricSpec("free_promocodes", "Промокодов ещё не введено", "Промокоды"),
    MetricSpec(
        "pool_activations",
        "Промокодов участвует в розыгрыше",
        "Ближайший розыгрыш",
    ),
    MetricSpec(
        "pool_unique_users",
        "Людей участвует в розыгрыше",
        "Ближайший розыгрыш",
    ),
    MetricSpec(
        "pool_activated_from",
        "Учитываются промокоды с",
        "Ближайший розыгрыш",
        MetricFormat.DATETIME,
    ),
    MetricSpec(
        "next_draw_at",
        "Когда следующий розыгрыш",
        "Ближайший розыгрыш",
        MetricFormat.DATETIME,
    ),
    MetricSpec(
        "winners_total",
        "Сколько раз выбрали победителя",
        "Итоги розыгрышей",
    ),
    MetricSpec(
        "winners_period",
        "Победителей за период",
        "Итоги розыгрышей",
    ),
    MetricSpec("winners_airpods", "Выдали AirPods", "Итоги розыгрышей"),
    MetricSpec("winners_ozon", "Выдали купон OZON", "Итоги розыгрышей"),
    MetricSpec(
        "days_without_full_draw",
        "Дней в периоде, когда выбрали меньше 2 победителей",
        "Итоги розыгрышей",
    ),
    MetricSpec(
        "attempts_period",
        "Ошибок ввода за период",
        "Ошибки ввода промокода",
    ),
    MetricSpec(
        "attempts_period_not_found",
        "За период: несуществующий код",
        "Ошибки ввода промокода",
    ),
    MetricSpec(
        "attempts_period_already_used",
        "За период: уже использованный код",
        "Ошибки ввода промокода",
    ),
)


def format_metric_value(
    value: Any,
    fmt: MetricFormat = MetricFormat.NUMBER,
) -> str:
    if value is None:
        return "—"
    if fmt is MetricFormat.DATETIME:
        if isinstance(value, datetime):
            return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")
        if isinstance(value, date):
            return value.strftime("%d.%m.%Y")
    if fmt is MetricFormat.DATE and isinstance(value, date | datetime):
        if isinstance(value, datetime):
            value = timezone.localtime(value).date()
        return value.strftime("%d.%m.%Y")
    return str(value)


def autofit_worksheet_columns(
    worksheet: Worksheet,
    *,
    min_width: float = 10,
    max_width: float = 60,
    padding: float = 2,
) -> None:
    """Подгоняет ширину колонок по содержимому текста."""
    for col_idx, column_cells in enumerate(worksheet.columns, start=1):
        max_len = 0
        for cell in column_cells:
            if cell.value is None:
                continue
            max_len = max(max_len, len(str(cell.value)))
        width = min(max_width, max(min_width, max_len + padding))
        worksheet.column_dimensions[get_column_letter(col_idx)].width = width


def resolve_metrics_period(
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[date, date]:
    """Возвращает включительный период; по умолчанию последние DAILY_SERIES_DAYS дней."""
    today = timezone.localdate()
    end = date_to or today
    start = date_from or (end - timedelta(days=DAILY_SERIES_DAYS - 1))
    if start > end:
        start, end = end, start
    span_days = (end - start).days + 1
    if span_days > MAX_METRICS_PERIOD_DAYS:
        start = end - timedelta(days=MAX_METRICS_PERIOD_DAYS - 1)
    return start, end


def period_datetime_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    """[start, end) в текущей таймзоне для фильтрации DateTimeField."""
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(date_from, time.min), tz)
    end_dt = timezone.make_aware(
        datetime.combine(date_to + timedelta(days=1), time.min),
        tz,
    )
    return start_dt, end_dt


class AnalyticsService:
    @staticmethod
    def summary(
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """Сводные метрики для админки."""
        start, end = resolve_metrics_period(date_from, date_to)
        start_dt, end_dt = period_datetime_bounds(start, end)
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

        attempts_period = PromoAttempt.objects.filter(
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        )
        activations_period = PromoActivation.objects.filter(
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        )

        draw_days_incomplete = (
            DailyDraw.objects.filter(date__gte=start, date__lte=end)
            .values("date")
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
            "activations_period": activations_period.count(),
            "free_promocodes": Promocode.objects.filter(is_taken=False).count(),
            "pool_activations": pool["count"],
            "pool_unique_users": pool["unique_users"],
            "pool_activated_from": pool["activated_from"],
            "next_draw_at": pool["next_draw_at"],
            "winners_total": DailyDraw.objects.filter(user__isnull=False).count(),
            "winners_period": DailyDraw.objects.filter(
                date__gte=start,
                date__lte=end,
                user__isnull=False,
            ).count(),
            "winners_airpods": DailyDraw.objects.filter(
                user__isnull=False, prize=Prize.AIRPODS
            ).count(),
            "winners_ozon": DailyDraw.objects.filter(
                user__isnull=False, prize=Prize.OZON_COUPON
            ).count(),
            "days_without_full_draw": draw_days_incomplete,
            "attempts_period": attempts_period.count(),
            "attempts_period_not_found": attempts_period.filter(
                reason=PromoAttemptReason.NOT_FOUND
            ).count(),
            "attempts_period_already_used": attempts_period.filter(
                reason=PromoAttemptReason.ALREADY_USED
            ).count(),
        }

    @staticmethod
    def summary_sections(
        metrics: dict[str, Any] | None = None,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        """Секции для UI/Excel: title + items (label, value, compact)."""
        stats = (
            metrics
            if metrics is not None
            else AnalyticsService.summary(date_from=date_from, date_to=date_to)
        )
        sections: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for spec in METRIC_SPECS:
            if current is None or current["title"] != spec.section:
                current = {"title": spec.section, "items": []}
                sections.append(current)
            raw = stats[spec.key]
            current["items"].append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "raw": raw,
                    "value": format_metric_value(raw, spec.fmt),
                    "compact": spec.fmt is not MetricFormat.NUMBER,
                }
            )
        return sections

    @staticmethod
    def daily_series(
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        """Посуточный ряд за выбранный период (включительно)."""
        start, end = resolve_metrics_period(date_from, date_to)
        tz = timezone.get_current_timezone()
        start_dt, end_dt = period_datetime_bounds(start, end)

        def counts_by_day(queryset) -> dict[date, int]:
            rows = (
                queryset.filter(created_at__gte=start_dt, created_at__lt=end_dt)
                .annotate(day=TruncDate("created_at", tzinfo=tz))
                .values("day")
                .annotate(c=Count("id"))
            )
            return {row["day"]: row["c"] for row in rows if row["day"] is not None}

        registrations = counts_by_day(User.objects.all())
        activations = counts_by_day(PromoActivation.objects.all())

        attempt_rows = (
            PromoAttempt.objects.filter(created_at__gte=start_dt, created_at__lt=end_dt)
            .annotate(day=TruncDate("created_at", tzinfo=tz))
            .values("day", "reason")
            .annotate(c=Count("id"))
        )
        attempts_total: dict[date, int] = {}
        attempts_not_found: dict[date, int] = {}
        attempts_already_used: dict[date, int] = {}
        for row in attempt_rows:
            day = row["day"]
            if day is None:
                continue
            attempts_total[day] = attempts_total.get(day, 0) + row["c"]
            if row["reason"] == PromoAttemptReason.NOT_FOUND:
                attempts_not_found[day] = row["c"]
            elif row["reason"] == PromoAttemptReason.ALREADY_USED:
                attempts_already_used[day] = row["c"]

        winners_by_day = {
            row["date"]: row["c"]
            for row in (
                DailyDraw.objects.filter(
                    date__gte=start,
                    date__lte=end,
                    user__isnull=False,
                )
                .values("date")
                .annotate(c=Count("id"))
            )
        }

        series: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            winners = winners_by_day.get(cursor, 0)
            series.append(
                {
                    "date": cursor,
                    "registrations": registrations.get(cursor, 0),
                    "activations": activations.get(cursor, 0),
                    "attempts": attempts_total.get(cursor, 0),
                    "attempts_not_found": attempts_not_found.get(cursor, 0),
                    "attempts_already_used": attempts_already_used.get(cursor, 0),
                    "winners": winners,
                    "draw_full": int(winners >= WINNERS_PER_DAY),
                }
            )
            cursor += timedelta(days=1)
        return series

    @staticmethod
    def export_analytics_as_excel(
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> tuple[bytes, str]:
        start, end = resolve_metrics_period(date_from, date_to)
        metrics = AnalyticsService.summary(date_from=start, date_to=end)
        summary_df = pd.DataFrame(
            [
                (spec.label, format_metric_value(metrics[spec.key], spec.fmt))
                for spec in METRIC_SPECS
            ],
            columns=["Показатель", "Значение"],
        )
        daily_df = pd.DataFrame(
            AnalyticsService.daily_series(date_from=start, date_to=end)
        ).rename(columns=DAILY_SERIES_COLUMNS)

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="Сводка", index=False)
            daily_df.to_excel(writer, sheet_name="По дням", index=False)
            for sheet in writer.sheets.values():
                autofit_worksheet_columns(sheet)

        filename = f"metrics-{start.isoformat()}_{end.isoformat()}.xlsx"
        return buffer.getvalue(), filename
