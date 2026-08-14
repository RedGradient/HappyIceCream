from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from auth.models import User
from promocode.exceptions import (
    PromocodeAlreadyUsed,
    PromocodeDoesNotExist,
    UserProfileIncomplete,
    WinnerAlreadySelectedToday,
)
from promocode.models import DailyDraw, PromoActivation, Promocode
from promocode.services import PromoCodeService, WinnerService


def _create_promocode(code: str) -> Promocode:
    return Promocode.objects.create(
        code=code,
        is_taken=False,
    )


def _create_user(**extra) -> User:
    defaults = {
        "username": "john_doe",
        "email": "john@example.com",
        "notify_on_promocode": True,
        "birth_date": date(1990, 1, 15),
        "telephone_number": "+79001234567",
    }
    defaults.update(extra)
    return User.objects.create(**defaults)


@patch.object(PromoCodeService, "_notify_on_promocode")
class PromocodeServiceTests(TestCase):
    def setUp(self):
        self.service = PromoCodeService()
        # Создаем пользователя
        self.user = _create_user()

    def test_apply_ok(self, notify_mock):
        # Создаем promocode в БД
        promocode = _create_promocode("ABCDEFGH")

        result = self.service.apply(promocode.code, self.user.id)

        user_promocode = PromoActivation.objects.get(
            user=self.user, promocode=promocode
        )
        self.assertEqual(user_promocode.user, result.user)
        self.assertEqual(user_promocode.promocode, result.promocode)
        self.assertEqual(user_promocode.created_at, result.created_at)
        self.assertIsNone(user_promocode.won_on)
        self.assertFalse(user_promocode.is_won)

        promocode.refresh_from_db()
        self.assertTrue(promocode.is_taken)

        # Проверяем, отправился ли email после успешного ввода
        notify_mock.assert_called_once_with(self.user, promocode)

    def test_apply_promo_not_exists(self, notify_mock):
        # Промокод, не существующий в БД
        promocode = "XXXXXXXX"

        with self.assertRaises(PromocodeDoesNotExist):
            self.service.apply(promocode, self.user.id)

        notify_mock.assert_not_called()

    def test_apply_promo_already_used(self, notify_mock):
        # Создаем пользователя 1, который заберет промокод
        user_1 = self.user
        # Создаем промокод
        promocode = _create_promocode("TAKENABC")
        # Пользователь 1 забирает промокод
        self.service.apply(promocode.code, user_1.id)

        # Создаем пользователя 2, которого ждет неприятный сюрприз
        user_2 = _create_user(username="alice", email="alice@example.com")
        # Пользователь 2 применяет промокод и получает ошибку
        with self.assertRaises(PromocodeAlreadyUsed):
            self.service.apply(promocode.code, user_2.id)

        self.assertEqual(notify_mock.call_count, 1)

    def test_apply_profile_incomplete(self, notify_mock):
        promocode = _create_promocode("ABCDEFGH")
        incomplete = _create_user(
            username="no_phone",
            email="nop@example.com",
            birth_date=None,
            telephone_number=None,
        )

        with self.assertRaises(UserProfileIncomplete):
            self.service.apply(promocode.code, incomplete.id)

        notify_mock.assert_not_called()
        promocode.refresh_from_db()
        self.assertFalse(promocode.is_taken)

    def test_user_promocodes_list(self, notify_mock):
        # Создаем и применяем промокоды
        codes = ["AAAAAAAA", "BBBBBBBB", "CCCCCCCC", "12345678", "87654321"]
        base_time = timezone.now()
        for index, code in enumerate(codes):
            _create_promocode(code)
            user_promocode = self.service.apply(code, self.user.id)
            # Фиксируем created_at, чтобы порядок в списке был стабильным
            PromoActivation.objects.filter(pk=user_promocode.pk).update(
                created_at=base_time + timedelta(seconds=index)
            )

        result = self.service.user_promocodes_list(self.user)

        self.assertEqual(len(result), len(codes))
        self.assertEqual([row["code"] for row in result], list(reversed(codes)))
        for row in result:
            self.assertIn("code", row)
            self.assertIn("created_at", row)
            self.assertIn("is_won", row)
            self.assertFalse(row["is_won"])


class WinnerServiceTests(TestCase):
    @patch.object(WinnerService, "_notify_winner")
    def test_get_random_winner_ok(self, notify_mock):
        """
        None если нет self.get_random_unused_promocode
        WinnerAlreadySelectedToday
        Побочные эффекты UserPromocode, promocode, DailyDraw
        Замокать self._notify_winner

        UserPromocode.DoesNotExist -> None

        IntegrityError ->
        """

        service = WinnerService()
        today = timezone.localdate()

        # Создание юзера и промокода
        user = _create_user()
        promocode = _create_promocode("ABCDEFGH")
        promocode.is_taken = True
        promocode.save(update_fields=["is_taken"])
        # Создаем связь UserPromocode
        user_promocode = PromoActivation.objects.create(
            user=user,
            promocode=promocode,
            # Розыгрыш происходит среди промо, использованных день назад
            created_at=timezone.now() - timedelta(days=1),
        )

        winner = service.get_random_winner()
        # Это чтобы утихомирить статический анализатор
        assert winner is not None

        self.assertIsNotNone(winner)
        self.assertEqual(user_promocode.user, winner.user)
        self.assertEqual(user_promocode.promocode.code, winner.promocode.code)

        user_promocode.refresh_from_db()
        self.assertTrue(user_promocode.is_won)
        self.assertEqual(user_promocode.won_on, today)

        promocode.refresh_from_db()
        self.assertTrue(promocode.is_taken)

        daily_draw = DailyDraw.objects.get(date=today)
        self.assertEqual(daily_draw.user_id, user.id)
        self.assertEqual(daily_draw.promocode_id, promocode.id)

        notify_mock.assert_called_once_with(user, promocode, today)

    def test_random_winner_winner_already_selected_today(self):
        # Не обязательно, чтобы user и promocode существовали,
        # главное - факт проведения розыгрыша
        DailyDraw.objects.create(user=None, promocode=None, date=timezone.localdate())

        with self.assertRaises(WinnerAlreadySelectedToday):
            WinnerService().get_random_winner()

    @patch.object(WinnerService, "_notify_winner")
    def test_random_winner_no_random_promocode(self, notify_mock):
        service = WinnerService()
        today = timezone.localdate()
        yesterday_draw = DailyDraw.objects.create(
            user=None,
            promocode=None,
            date=today - timedelta(days=1),
        )

        # Случайный промокод должен быть None
        service._get_random_promocode = MagicMock()
        service._get_random_promocode.return_value = None

        # Тогда результат будет None
        winner = service.get_random_winner()
        self.assertIsNone(winner)

        daily_draw = DailyDraw.objects.get(date=today)
        self.assertEqual(daily_draw.date, today)
        self.assertIsNone(daily_draw.user)
        self.assertIsNone(daily_draw.promocode)
        self.assertEqual(DailyDraw.objects.count(), 2)

        service._get_random_promocode.assert_called_once_with(
            activated_from=yesterday_draw.created_at,
        )
        notify_mock.assert_not_called()

    @patch.object(WinnerService, "_notify_winner")
    def test_random_winner_user_promocode_not_exists(self, notify_mock):
        service = WinnerService()
        today = timezone.localdate()
        DailyDraw.objects.create(
            user=None,
            promocode=None,
            date=today - timedelta(days=1),
        )

        missing = MagicMock()
        missing.pk = 999_999
        missing.id = 999_999
        missing.promocode_id = 1
        service._get_random_promocode = MagicMock(return_value=missing)

        winner = service.get_random_winner()
        self.assertIsNone(winner)

        daily_draw = DailyDraw.objects.get(date=today)
        self.assertIsNone(daily_draw.user)
        self.assertIsNone(daily_draw.promocode)
        self.assertEqual(DailyDraw.objects.count(), 2)

        notify_mock.assert_not_called()

    @patch.object(WinnerService, "_notify_winner")
    def test_random_winner_integrity_error_closes_day_without_winner(self, notify_mock):
        service = WinnerService()
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        # Пользователь уже побеждал раньше
        user = _create_user()
        user.winner = True
        user.save(update_fields=["winner"])
        old_promo = _create_promocode("AAAAAAAA")
        old_promo.is_taken = True
        old_promo.save(update_fields=["is_taken"])
        PromoActivation.objects.create(
            user=user,
            promocode=old_promo,
            is_won=True,
            won_on=yesterday,
            created_at=timezone.now() - timedelta(days=2),
        )

        # Кандидат на сегодняшнюю победу — тот же пользователь
        candidate = _create_promocode("BBBBBBBB")
        candidate.is_taken = True
        candidate.save(update_fields=["is_taken"])
        PromoActivation.objects.create(
            user=user,
            promocode=candidate,
            # Розыгрыш происходит среди промо, использованных день назад
            created_at=timezone.now() - timedelta(days=1),
        )

        winner = service.get_random_winner()
        self.assertIsNone(winner)

        daily_draw = DailyDraw.objects.get(date=today)
        self.assertIsNone(daily_draw.user)
        self.assertIsNone(daily_draw.promocode)
        self.assertEqual(DailyDraw.objects.count(), 1)

        notify_mock.assert_not_called()

    @patch.object(WinnerService, "_notify_winner")
    def test_clear_today_draw_allows_redo(self, notify_mock):
        service = WinnerService()
        today = timezone.localdate()

        user = _create_user()
        promocode = _create_promocode("ABCDEFGH")
        promocode.is_taken = True
        promocode.save(update_fields=["is_taken"])
        activation = PromoActivation.objects.create(
            user=user,
            promocode=promocode,
            created_at=timezone.now() - timedelta(days=1),
        )

        winner = service.get_random_winner()
        self.assertIsNotNone(winner)
        self.assertTrue(DailyDraw.objects.filter(date=today).exists())

        cleared = WinnerService.clear_today_draw()
        self.assertTrue(cleared)
        self.assertFalse(DailyDraw.objects.filter(date=today).exists())

        activation.refresh_from_db()
        user.refresh_from_db()
        self.assertFalse(activation.is_won)
        self.assertIsNone(activation.won_on)
        self.assertFalse(user.winner)

        redo = service.get_random_winner()
        self.assertIsNotNone(redo)
        self.assertTrue(DailyDraw.objects.filter(date=today).exists())
