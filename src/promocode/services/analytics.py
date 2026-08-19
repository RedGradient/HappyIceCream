import io
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from auth.models import User
from promocode.models import (
    DailyDraw,
    Prize,
    PromoActivation,
    PromoAttempt,
    PromoAttemptReason,
)

DAILY_SERIES_DAYS = 30
MAX_METRICS_PERIOD_DAYS = 366
# В админке таблицы «по дням» показывают только хвост периода.
ADMIN_DAILY_ROWS_LIMIT = 15

FUNNEL_BY_DAY_COLUMNS: dict[str, str] = {
    "date": "Дата",
    "registrations": "Рег.",
    "email_confirmed": "Email",
    "email_pct": "Email %",
    "profile_complete": "Профиль",
    "profile_pct": "Профиль %",
    "with_promocode": "Промокод",
    "promo_pct": "Промокод %",
    "winners": "Победа",
    "win_pct": "Победа %",
}

PRIZES_BY_DAY_COLUMNS: dict[str, str] = {
    "date": "Дата",
    "airpods": "AirPods",
    "ozon": "OZON",
    "total": "Всего",
}

ATTEMPTS_BY_DAY_COLUMNS: dict[str, str] = {
    "date": "Дата",
    "total": "Всего",
    "not_found": "Не найден",
    "already_used": "Уже использован",
}


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


def bold_worksheet_header_rows(worksheet: Worksheet, *row_numbers: int) -> None:
    """Делает жирным шрифт в указанных строках (обычно заголовки)."""
    bold = Font(bold=True)
    for row_number in row_numbers:
        for cell in worksheet[row_number]:
            cell.font = bold


def truncate_daily_rows(
    rows: list[Any],
    *,
    limit: int = ADMIN_DAILY_ROWS_LIMIT,
) -> list[Any]:
    """Оставляет последние limit строк (для UI админки)."""
    if limit <= 0 or len(rows) <= limit:
        return rows
    return rows[-limit:]


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


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * part / whole, 1)


def _profile_complete_q() -> Q:
    return (
        Q(email_confirmed=True)
        & Q(birth_date__isnull=False)
        & ~Q(first_name="")
        & Q(first_name__isnull=False)
        & ~Q(last_name="")
        & Q(last_name__isnull=False)
        & ~Q(telephone_number__isnull=True)
        & ~Q(telephone_number="")
    )


def _is_profile_complete(user: dict[str, Any]) -> bool:
    """Проверка заполненности профиля по полям из values()-словаря."""
    if not user.get("email_confirmed"):
        return False
    if user.get("birth_date") is None:
        return False
    first_name = (user.get("first_name") or "").strip()
    last_name = (user.get("last_name") or "").strip()
    telephone = (user.get("telephone_number") or "").strip()
    return bool(first_name and last_name and telephone)


class AnalyticsService:
    @staticmethod
    def dashboard(
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """Данные страницы метрик: 5 блоков (админка + Excel)."""
        start, end = resolve_metrics_period(date_from, date_to)
        return {
            "period_from": start,
            "period_to": end,
            "funnel_all_time": AnalyticsService.funnel_all_time(),
            "funnel_by_day": AnalyticsService.funnel_by_day(
                date_from=start,
                date_to=end,
            ),
            "prizes_all_time": AnalyticsService.prizes_all_time(),
            "prizes_by_day": AnalyticsService.prizes_by_day(
                date_from=start,
                date_to=end,
            ),
            "attempts_summary": AnalyticsService.attempts_summary(
                date_from=start,
                date_to=end,
            ),
            "attempts_by_day": AnalyticsService.attempts_by_day(
                date_from=start,
                date_to=end,
            ),
        }

    @staticmethod
    def funnel_all_time() -> list[dict[str, Any]]:
        """Воронка за всё время (карточки)."""
        registered = User.objects.count()
        email_confirmed = User.objects.filter(email_confirmed=True).count()
        profile_complete = User.objects.filter(_profile_complete_q()).count()
        with_promocode = (
            User.objects.filter(user_promocodes__isnull=False).distinct().count()
        )
        winners = User.objects.filter(winner=True).count()

        steps = [
            ("Зарегистрировались", registered),
            ("Подтвердили email", email_confirmed),
            ("Профиль заполнен", profile_complete),
            ("Ввели ≥1 промокод", with_promocode),
            ("Победители", winners),
        ]
        return [
            {
                "label": label,
                "count": count,
                "pct": _pct(count, registered),
            }
            for label, count in steps
        ]

    @staticmethod
    def funnel_by_day(
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        """
        Когортная воронка по дням регистрации.

        Для пользователей, зарегистрированных в день D, считаем, сколько
        из них сейчас подтвердили email / заполнили профиль / ввели промокод /
        стали победителями. % — от числа регистраций в этот день.
        """
        start, end = resolve_metrics_period(date_from, date_to)
        start_dt, end_dt = period_datetime_bounds(start, end)
        tz = timezone.get_current_timezone()

        users = list(
            User.objects.filter(created_at__gte=start_dt, created_at__lt=end_dt)
            .annotate(day=TruncDate("created_at", tzinfo=tz))
            .values(
                "id",
                "day",
                "email_confirmed",
                "first_name",
                "last_name",
                "birth_date",
                "telephone_number",
                "winner",
            )
        )
        promo_user_ids = set(
            PromoActivation.objects.filter(
                user_id__in=[user["id"] for user in users]
            ).values_list("user_id", flat=True)
        )

        by_day: dict[date, dict[str, int]] = {}
        for user in users:
            day = user["day"]
            if day is None:
                continue
            bucket = by_day.setdefault(
                day,
                {
                    "registrations": 0,
                    "email_confirmed": 0,
                    "profile_complete": 0,
                    "with_promocode": 0,
                    "winners": 0,
                },
            )
            bucket["registrations"] += 1
            if user["email_confirmed"]:
                bucket["email_confirmed"] += 1
            if _is_profile_complete(user):
                bucket["profile_complete"] += 1
            if user["id"] in promo_user_ids:
                bucket["with_promocode"] += 1
            if user["winner"]:
                bucket["winners"] += 1

        series: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            bucket = by_day.get(
                cursor,
                {
                    "registrations": 0,
                    "email_confirmed": 0,
                    "profile_complete": 0,
                    "with_promocode": 0,
                    "winners": 0,
                },
            )
            reg = bucket["registrations"]
            series.append(
                {
                    "date": cursor,
                    "registrations": reg,
                    "email_confirmed": bucket["email_confirmed"],
                    "email_pct": _pct(bucket["email_confirmed"], reg),
                    "profile_complete": bucket["profile_complete"],
                    "profile_pct": _pct(bucket["profile_complete"], reg),
                    "with_promocode": bucket["with_promocode"],
                    "promo_pct": _pct(bucket["with_promocode"], reg),
                    "winners": bucket["winners"],
                    "win_pct": _pct(bucket["winners"], reg),
                }
            )
            cursor += timedelta(days=1)
        return series

    @staticmethod
    def prizes_all_time() -> dict[str, int]:
        airpods = DailyDraw.objects.filter(
            user__isnull=False,
            prize=Prize.AIRPODS,
        ).count()
        ozon = DailyDraw.objects.filter(
            user__isnull=False,
            prize=Prize.OZON_COUPON,
        ).count()
        return {
            "airpods": airpods,
            "ozon": ozon,
            "total": airpods + ozon,
        }

    @staticmethod
    def prizes_by_day(
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        start, end = resolve_metrics_period(date_from, date_to)
        rows = (
            DailyDraw.objects.filter(
                date__gte=start,
                date__lte=end,
                user__isnull=False,
            )
            .values("date")
            .annotate(
                airpods=Count("id", filter=Q(prize=Prize.AIRPODS)),
                ozon=Count("id", filter=Q(prize=Prize.OZON_COUPON)),
                total=Count("id"),
            )
        )
        by_day = {row["date"]: row for row in rows}

        series: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            row = by_day.get(cursor)
            series.append(
                {
                    "date": cursor,
                    "airpods": row["airpods"] if row else 0,
                    "ozon": row["ozon"] if row else 0,
                    "total": row["total"] if row else 0,
                }
            )
            cursor += timedelta(days=1)
        return series

    @staticmethod
    def attempts_summary(
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, int]:
        start, end = resolve_metrics_period(date_from, date_to)
        start_dt, end_dt = period_datetime_bounds(start, end)
        qs = PromoAttempt.objects.filter(
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        )
        return {
            "total": qs.count(),
            "not_found": qs.filter(reason=PromoAttemptReason.NOT_FOUND).count(),
            "already_used": qs.filter(reason=PromoAttemptReason.ALREADY_USED).count(),
        }

    @staticmethod
    def attempts_by_day(
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        start, end = resolve_metrics_period(date_from, date_to)
        start_dt, end_dt = period_datetime_bounds(start, end)
        tz = timezone.get_current_timezone()

        attempt_rows = (
            PromoAttempt.objects.filter(created_at__gte=start_dt, created_at__lt=end_dt)
            .annotate(day=TruncDate("created_at", tzinfo=tz))
            .values("day", "reason")
            .annotate(c=Count("id"))
        )
        totals: dict[date, int] = {}
        not_found: dict[date, int] = {}
        already_used: dict[date, int] = {}
        for row in attempt_rows:
            day = row["day"]
            if day is None:
                continue
            totals[day] = totals.get(day, 0) + row["c"]
            if row["reason"] == PromoAttemptReason.NOT_FOUND:
                not_found[day] = row["c"]
            elif row["reason"] == PromoAttemptReason.ALREADY_USED:
                already_used[day] = row["c"]

        series: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            series.append(
                {
                    "date": cursor,
                    "total": totals.get(cursor, 0),
                    "not_found": not_found.get(cursor, 0),
                    "already_used": already_used.get(cursor, 0),
                }
            )
            cursor += timedelta(days=1)
        return series

    @staticmethod
    def export_analytics_as_excel(
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> tuple[bytes, str]:
        data = AnalyticsService.dashboard(date_from=date_from, date_to=date_to)
        start = data["period_from"]
        end = data["period_to"]

        funnel_df = pd.DataFrame(
            [
                (row["label"], row["count"], row["pct"])
                for row in data["funnel_all_time"]
            ],
            columns=["Шаг", "Значение", "% от регистраций"],
        )

        funnel_by_day_df = pd.DataFrame(data["funnel_by_day"]).rename(
            columns=FUNNEL_BY_DAY_COLUMNS
        )
        if funnel_by_day_df.empty:
            funnel_by_day_df = pd.DataFrame(
                columns=list(FUNNEL_BY_DAY_COLUMNS.values())
            )

        prizes = data["prizes_all_time"]
        prizes_df = pd.DataFrame(
            [
                ("AirPods", prizes["airpods"]),
                ("Купон OZON", prizes["ozon"]),
                ("Всего призов", prizes["total"]),
            ],
            columns=["Приз", "Значение"],
        )

        prizes_by_day_df = pd.DataFrame(data["prizes_by_day"]).rename(
            columns=PRIZES_BY_DAY_COLUMNS
        )
        if prizes_by_day_df.empty:
            prizes_by_day_df = pd.DataFrame(
                columns=list(PRIZES_BY_DAY_COLUMNS.values())
            )

        attempts = data["attempts_summary"]
        attempts_summary_df = pd.DataFrame(
            [
                ("Всего ошибок", attempts["total"]),
                ("Код не найден", attempts["not_found"]),
                ("Уже использован", attempts["already_used"]),
            ],
            columns=["Показатель", "Значение"],
        )
        attempts_by_day_df = pd.DataFrame(data["attempts_by_day"]).rename(
            columns=ATTEMPTS_BY_DAY_COLUMNS
        )
        if attempts_by_day_df.empty:
            attempts_by_day_df = pd.DataFrame(
                columns=list(ATTEMPTS_BY_DAY_COLUMNS.values())
            )

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            funnel_df.to_excel(writer, sheet_name="Воронка (всего)", index=False)
            funnel_by_day_df.to_excel(writer, sheet_name="Воронка по дням", index=False)
            prizes_df.to_excel(writer, sheet_name="Призы", index=False)
            prizes_by_day_df.to_excel(writer, sheet_name="Призы по дням", index=False)

            attempts_summary_df.to_excel(
                writer, sheet_name="Неудачные попытки", index=False
            )
            attempts_daily_header_row = len(attempts_summary_df) + 4
            attempts_by_day_df.to_excel(
                writer,
                sheet_name="Неудачные попытки",
                index=False,
                startrow=attempts_daily_header_row - 1,
            )
            for sheet_name, sheet in writer.sheets.items():
                autofit_worksheet_columns(sheet)
                if sheet_name == "Неудачные попытки":
                    bold_worksheet_header_rows(sheet, 1, attempts_daily_header_row)
                else:
                    bold_worksheet_header_rows(sheet, 1)

        filename = f"metrics-{start.isoformat()}_{end.isoformat()}.xlsx"
        return buffer.getvalue(), filename
