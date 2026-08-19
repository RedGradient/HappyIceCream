import io
from datetime import timedelta

import pandas as pd
from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook

from auth.models import User
from promocode.models import (
    DailyDraw,
    Prize,
    PromoActivation,
    PromoAttempt,
    PromoAttemptReason,
)
from promocode.services.analytics import (
    FUNNEL_BY_DAY_COLUMNS,
    PRIZES_BY_DAY_COLUMNS,
    AnalyticsService,
    period_datetime_bounds,
    truncate_daily_rows,
)
from promocode.tests.helpers import create_promocode, create_user


class AnalyticsServiceTests(TestCase):
    def test_funnel_prizes_and_attempts(self):
        complete = create_user(
            username="complete",
            email="complete@example.com",
            first_name="John",
            last_name="Doe",
            email_confirmed=True,
        )
        create_user(
            username="incomplete",
            email="incomplete@example.com",
            first_name="",
            last_name="",
            birth_date=None,
            telephone_number="",
            email_confirmed=False,
        )

        promo = create_promocode("ABCDEFGH")
        promo.is_taken = True
        promo.save(update_fields=["is_taken"])
        PromoActivation.objects.create(user=complete, promocode=promo)

        PromoAttempt.objects.create(
            user=complete,
            attempted_code="WRONGCOD",
            reason=PromoAttemptReason.NOT_FOUND,
            ip_address="127.0.0.1",
            user_agent="test",
        )
        PromoAttempt.objects.create(
            user=complete,
            attempted_code="USEDCODE",
            reason=PromoAttemptReason.ALREADY_USED,
            ip_address="127.0.0.1",
            user_agent="test",
        )

        funnel = {row["label"]: row for row in AnalyticsService.funnel_all_time()}
        self.assertEqual(funnel["Зарегистрировались"]["count"], 2)
        self.assertEqual(funnel["Подтвердили email"]["count"], 1)
        self.assertEqual(funnel["Профиль заполнен"]["count"], 1)
        self.assertEqual(funnel["Ввели ≥1 промокод"]["count"], 1)
        self.assertEqual(funnel["Победители"]["count"], 0)

        attempts = AnalyticsService.attempts_summary()
        self.assertEqual(attempts["total"], 2)
        self.assertEqual(attempts["not_found"], 1)
        self.assertEqual(attempts["already_used"], 1)

        today = timezone.localdate()
        DailyDraw.objects.create(
            date=today,
            place=1,
            prize=Prize.AIRPODS,
            user=complete,
            promocode=promo,
        )
        complete.winner = True
        complete.save(update_fields=["winner"])

        prizes = AnalyticsService.prizes_all_time()
        self.assertEqual(prizes["airpods"], 1)
        self.assertEqual(prizes["ozon"], 0)
        self.assertEqual(prizes["total"], 1)

        funnel_after = {row["label"]: row for row in AnalyticsService.funnel_all_time()}
        self.assertEqual(funnel_after["Победители"]["count"], 1)

    def test_funnel_by_day_cohort(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        advanced = create_user(
            username="advanced",
            email="advanced@example.com",
            first_name="Ann",
            last_name="Lee",
            email_confirmed=True,
            winner=True,
        )
        plain = create_user(
            username="plain",
            email="plain@example.com",
            first_name="",
            last_name="",
            birth_date=None,
            telephone_number="",
            email_confirmed=False,
        )
        # Оба зарегистрированы «сегодня» в рамках теста
        User.objects.filter(pk__in=[advanced.pk, plain.pk]).update(
            created_at=timezone.now(),
        )

        older = create_user(
            username="older",
            email="older@example.com",
            first_name="Old",
            last_name="User",
            email_confirmed=True,
        )
        # Переносим created_at на вчера
        start_dt, _ = period_datetime_bounds(yesterday, yesterday)
        User.objects.filter(pk=older.pk).update(created_at=start_dt)

        promo = create_promocode("COHORT01")
        promo.is_taken = True
        promo.save(update_fields=["is_taken"])
        PromoActivation.objects.create(user=advanced, promocode=promo)

        series = AnalyticsService.funnel_by_day(
            date_from=yesterday,
            date_to=today,
        )
        self.assertEqual(len(series), 2)

        day_yesterday = series[0]
        self.assertEqual(day_yesterday["date"], yesterday)
        self.assertEqual(day_yesterday["registrations"], 1)
        self.assertEqual(day_yesterday["email_confirmed"], 1)
        self.assertEqual(day_yesterday["email_pct"], 100.0)
        self.assertEqual(day_yesterday["with_promocode"], 0)
        self.assertEqual(day_yesterday["winners"], 0)

        day_today = series[1]
        self.assertEqual(day_today["date"], today)
        self.assertEqual(day_today["registrations"], 2)
        self.assertEqual(day_today["email_confirmed"], 1)
        self.assertEqual(day_today["email_pct"], 50.0)
        self.assertEqual(day_today["profile_complete"], 1)
        self.assertEqual(day_today["profile_pct"], 50.0)
        self.assertEqual(day_today["with_promocode"], 1)
        self.assertEqual(day_today["promo_pct"], 50.0)
        self.assertEqual(day_today["winners"], 1)
        self.assertEqual(day_today["win_pct"], 50.0)

    def test_dashboard_period_and_excel_sheets(self):
        today = timezone.localdate()
        user = create_user(username="daily", email="daily@example.com")
        promo = create_promocode("DAILY001")
        promo.is_taken = True
        promo.save(update_fields=["is_taken"])
        PromoActivation.objects.create(user=user, promocode=promo)
        PromoAttempt.objects.create(
            user=user,
            attempted_code="WRONGCOD",
            reason=PromoAttemptReason.NOT_FOUND,
            ip_address="127.0.0.1",
            user_agent="test",
        )
        DailyDraw.objects.create(
            date=today,
            place=1,
            prize=Prize.AIRPODS,
            user=user,
            promocode=promo,
        )

        start = today - timedelta(days=6)
        data = AnalyticsService.dashboard(date_from=start, date_to=today)
        self.assertEqual(data["period_from"], start)
        self.assertEqual(data["period_to"], today)
        self.assertEqual(len(data["funnel_by_day"]), 7)
        self.assertEqual(data["funnel_by_day"][-1]["date"], today)
        self.assertEqual(data["funnel_by_day"][-1]["registrations"], 1)
        self.assertEqual(data["funnel_by_day"][-1]["with_promocode"], 1)
        self.assertEqual(data["funnel_by_day"][-1]["promo_pct"], 100.0)
        self.assertEqual(data["prizes_by_day"][-1]["airpods"], 1)
        self.assertEqual(data["attempts_by_day"][-1]["total"], 1)
        self.assertEqual(data["attempts_by_day"][-1]["not_found"], 1)

        content, filename = AnalyticsService.export_analytics_as_excel(
            date_from=start,
            date_to=today,
        )
        self.assertEqual(
            filename,
            f"metrics-{start.isoformat()}_{today.isoformat()}.xlsx",
        )

        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
        self.assertEqual(
            set(sheets),
            {
                "Воронка (всего)",
                "Воронка по дням",
                "Призы",
                "Призы по дням",
                "Неудачные попытки",
            },
        )
        self.assertEqual(
            list(sheets["Воронка (всего)"].columns),
            ["Шаг", "Значение", "% от регистраций"],
        )
        self.assertEqual(len(sheets["Воронка по дням"]), 7)
        self.assertEqual(
            list(sheets["Воронка по дням"].columns),
            list(FUNNEL_BY_DAY_COLUMNS.values()),
        )
        self.assertEqual(
            list(sheets["Призы по дням"].columns),
            list(PRIZES_BY_DAY_COLUMNS.values()),
        )
        self.assertEqual(
            list(sheets["Неудачные попытки"].columns)[:2],
            ["Показатель", "Значение"],
        )

        workbook = load_workbook(io.BytesIO(content))
        funnel_sheet = workbook["Воронка (всего)"]
        self.assertGreater(funnel_sheet.column_dimensions["A"].width, 10)
        self.assertTrue(funnel_sheet["A1"].font.bold)
        self.assertTrue(workbook["Воронка по дням"]["A1"].font.bold)
        self.assertTrue(workbook["Неудачные попытки"]["A1"].font.bold)

        # Excel без усечения: длинный период целиком
        long_start = today - timedelta(days=20)
        long_content, _ = AnalyticsService.export_analytics_as_excel(
            date_from=long_start,
            date_to=today,
        )
        long_sheets = pd.read_excel(io.BytesIO(long_content), sheet_name=None)
        self.assertEqual(len(long_sheets["Воронка по дням"]), 21)
        self.assertEqual(
            len(truncate_daily_rows(data["funnel_by_day"], limit=15)),
            7,
        )
        truncated = truncate_daily_rows(
            AnalyticsService.funnel_by_day(date_from=long_start, date_to=today)
        )
        self.assertEqual(len(truncated), 15)
        self.assertEqual(truncated[-1]["date"], today)
        self.assertEqual(truncated[0]["date"], today - timedelta(days=14))

        outside = today - timedelta(days=40)
        attempts_outside = AnalyticsService.attempts_summary(
            date_from=outside,
            date_to=outside,
        )
        self.assertEqual(attempts_outside["total"], 0)
        prizes_outside = AnalyticsService.prizes_by_day(
            date_from=outside,
            date_to=outside,
        )
        self.assertEqual(prizes_outside[0]["total"], 0)
