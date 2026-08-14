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
from promocode.services import DAILY_PRIZES, PromoCodeService, WinnerService


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
        service = WinnerService()
        today = timezone.localdate()

        user1 = _create_user(username="alice", email="alice@example.com")
        user2 = _create_user(username="bob", email="bob@example.com")
        promo1 = _create_promocode("ABCDEFGH")
        promo1.is_taken = True
        promo1.save(update_fields=["is_taken"])
        promo2 = _create_promocode("HGFEEDCB")
        promo2.is_taken = True
        promo2.save(update_fields=["is_taken"])
        PromoActivation.objects.create(
            user=user1,
            promocode=promo1,
            created_at=timezone.now() - timedelta(days=1),
        )
        PromoActivation.objects.create(
            user=user2,
            promocode=promo2,
            created_at=timezone.now() - timedelta(days=1),
        )

        winners = service.get_random_winner()

        self.assertEqual(len(winners), 2)
        self.assertEqual(
            {w.user_id for w in winners},
            {user1.id, user2.id},
        )
        self.assertEqual(
            {w.prize for w in winners},
            set(DAILY_PRIZES),
        )

        draws = list(DailyDraw.objects.filter(date=today).order_by("place"))
        self.assertEqual(len(draws), 2)
        self.assertEqual([d.place for d in draws], [1, 2])
        self.assertTrue(all(d.user_id for d in draws))
        self.assertTrue(all(d.prize for d in draws))

        notify_mock.assert_called()
        self.assertEqual(notify_mock.call_count, 2)
        for call in notify_mock.call_args_list:
            self.assertIn(call.args[3], ("AirPods", "Купон OZON"))

    def test_random_winner_winner_already_selected_today(self):
        DailyDraw.objects.create(
            user=None,
            promocode=None,
            date=timezone.localdate(),
            place=1,
        )

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
            place=1,
        )

        service._get_random_promocode = MagicMock(return_value=None)

        winners = service.get_random_winner()
        self.assertEqual(winners, [])

        draws = list(DailyDraw.objects.filter(date=today).order_by("place"))
        self.assertEqual(len(draws), 2)
        self.assertTrue(all(d.user_id is None for d in draws))
        self.assertEqual(DailyDraw.objects.count(), 3)

        self.assertEqual(service._get_random_promocode.call_count, 2)
        service._get_random_promocode.assert_called_with(
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
            place=1,
        )

        missing = MagicMock()
        missing.pk = 999_999
        missing.id = 999_999
        missing.promocode_id = 1
        service._get_random_promocode = MagicMock(return_value=missing)

        winners = service.get_random_winner()
        self.assertEqual(winners, [])

        draws = list(DailyDraw.objects.filter(date=today).order_by("place"))
        self.assertEqual(len(draws), 2)
        self.assertTrue(all(d.user_id is None for d in draws))
        self.assertEqual(DailyDraw.objects.count(), 3)

        notify_mock.assert_not_called()

    @patch.object(WinnerService, "_notify_winner")
    def test_random_winner_integrity_error_closes_day_without_winner(self, notify_mock):
        service = WinnerService()
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

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

        candidate = _create_promocode("BBBBBBBB")
        candidate.is_taken = True
        candidate.save(update_fields=["is_taken"])
        PromoActivation.objects.create(
            user=user,
            promocode=candidate,
            created_at=timezone.now() - timedelta(days=1),
        )

        winners = service.get_random_winner()
        self.assertEqual(winners, [])

        draws = list(DailyDraw.objects.filter(date=today).order_by("place"))
        self.assertEqual(len(draws), 2)
        self.assertTrue(all(d.user_id is None for d in draws))
        self.assertEqual(DailyDraw.objects.count(), 2)

        notify_mock.assert_not_called()

    @patch.object(WinnerService, "_notify_winner")
    def test_get_random_winner_one_candidate_fills_only_one_place(self, notify_mock):
        service = WinnerService()
        today = timezone.localdate()

        user = _create_user()
        promocode = _create_promocode("ABCDEFGH")
        promocode.is_taken = True
        promocode.save(update_fields=["is_taken"])
        PromoActivation.objects.create(
            user=user,
            promocode=promocode,
            created_at=timezone.now() - timedelta(days=1),
        )

        winners = service.get_random_winner()
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].user_id, user.id)
        self.assertIn(winners[0].prize, DAILY_PRIZES)

        draws = list(DailyDraw.objects.filter(date=today).order_by("place"))
        self.assertEqual(len(draws), 2)
        self.assertEqual(draws[0].user_id, user.id)
        self.assertIsNotNone(draws[0].prize)
        self.assertIsNone(draws[1].user_id)
        self.assertIsNone(draws[1].prize)
        notify_mock.assert_called_once()
        self.assertIn(notify_mock.call_args.args[3], ("AirPods", "Купон OZON"))

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

        winners = service.get_random_winner()
        self.assertEqual(len(winners), 1)
        self.assertEqual(DailyDraw.objects.filter(date=today).count(), 2)

        cleared = WinnerService.clear_today_draw()
        self.assertTrue(cleared)
        self.assertFalse(DailyDraw.objects.filter(date=today).exists())

        activation.refresh_from_db()
        user.refresh_from_db()
        self.assertFalse(activation.is_won)
        self.assertIsNone(activation.won_on)
        self.assertFalse(user.winner)

        redo = service.get_random_winner()
        self.assertEqual(len(redo), 1)
        self.assertEqual(DailyDraw.objects.filter(date=today).count(), 2)


class CabinetServiceTests(TestCase):
    def setUp(self):
        self.user = _create_user(
            first_name="John",
            last_name="Doe",
            email_confirmed=True,
        )

    def test_participation_counts_codes_in_current_pool(self):
        from promocode.services import CabinetService

        promo = _create_promocode("ABCDEFGH")
        PromoActivation.objects.create(user=self.user, promocode=promo)

        data = CabinetService().participation(self.user)
        self.assertEqual(data["codes_count"], 1)
        self.assertTrue(data["eligible"])
        self.assertFalse(data["already_won"])
        self.assertEqual(data["collection_until"], data["next_draw_at"])

    def test_participation_zero_if_already_won(self):
        from promocode.services import CabinetService

        self.user.winner = True
        self.user.save(update_fields=["winner"])
        promo = _create_promocode("ABCDEFGH")
        PromoActivation.objects.create(user=self.user, promocode=promo)

        data = CabinetService().participation(self.user)
        self.assertEqual(data["codes_count"], 0)
        self.assertTrue(data["already_won"])

    def test_checklist(self):
        from promocode.services import CabinetService

        checklist = CabinetService.profile_checklist(self.user)
        self.assertTrue(checklist["complete"])

        incomplete = _create_user(
            username="no_phone",
            email="nophone@example.com",
            first_name="A",
            last_name="B",
            birth_date=None,
            telephone_number="",
            email_confirmed=False,
        )
        checklist = CabinetService.profile_checklist(incomplete)
        self.assertFalse(checklist["complete"])
        self.assertEqual(checklist["done_count"], 1)

    def test_cabinet_api(self):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.get("/api/cabinet/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("participation", response.data)
        self.assertIn("checklist", response.data)
        self.assertNotIn("wins", response.data)


class PromoCooldownTests(TestCase):
    def setUp(self):
        self.user = _create_user(
            first_name="John",
            last_name="Doe",
            email_confirmed=True,
        )
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_cooldown_after_three_failures_within_one_minute(self):
        for _ in range(3):
            response = self.client.post(
                "/promocode",
                {"code": "WRONGCOD"},
                format="json",
            )
            self.assertIn(response.status_code, (404, 409, 400))

        locked = self.client.post(
            "/promocode",
            {"code": "WRONGCOD"},
            format="json",
        )
        self.assertEqual(locked.status_code, 429)

    def test_no_cooldown_if_failures_are_spread_out(self):
        from promocode import views as promo_views

        session = self.client.session
        old = timezone.now() - timedelta(seconds=61)
        session[promo_views.SESSION_FAILED_ATTEMPTS] = [
            old.isoformat(),
            old.isoformat(),
        ]
        session.save()

        response = self.client.post(
            "/promocode",
            {"code": "WRONGCOD"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(promo_views.SESSION_COOLDOWN_UNTIL, self.client.session)
