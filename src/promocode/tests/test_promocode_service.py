from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from promocode.exceptions import (
    PromocodeAlreadyUsed,
    PromocodeDoesNotExist,
    UserProfileIncomplete,
)
from promocode.models import DailyDraw, Prize, PromoActivation
from promocode.services.promocode import PromoCodeService
from promocode.tests.helpers import create_promocode, create_user


@patch.object(PromoCodeService, "_notify_on_promocode")
class PromocodeServiceTests(TestCase):
    def setUp(self):
        self.service = PromoCodeService()
        # Создаем пользователя
        self.user = create_user()

    def test_apply_ok(self, notify_mock):
        # Создаем promocode в БД
        promocode = create_promocode("ABCDEFGH")

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
        promocode = create_promocode("TAKENABC")
        # Пользователь 1 забирает промокод
        self.service.apply(promocode.code, user_1.id)

        # Создаем пользователя 2, которого ждет неприятный сюрприз
        user_2 = create_user(username="alice", email="alice@example.com")
        # Пользователь 2 применяет промокод и получает ошибку
        with self.assertRaises(PromocodeAlreadyUsed):
            self.service.apply(promocode.code, user_2.id)

        self.assertEqual(notify_mock.call_count, 1)

    def test_apply_profile_incomplete(self, notify_mock):
        promocode = create_promocode("ABCDEFGH")
        incomplete = create_user(
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
            create_promocode(code)
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
            self.assertIn("in_pool", row)
            self.assertFalse(row["is_won"])
            self.assertTrue(row["in_pool"])

    def test_user_promocodes_list_marks_stale_codes(self, notify_mock):
        old_promo = create_promocode("OLDPROMO")
        old_promo.is_taken = True
        old_promo.save(update_fields=["is_taken"])
        old_activation = PromoActivation.objects.create(
            user=self.user,
            promocode=old_promo,
        )
        PromoActivation.objects.filter(pk=old_activation.pk).update(
            created_at=timezone.now() - timedelta(days=2),
        )

        DailyDraw.objects.create(
            date=timezone.localdate() - timedelta(days=1),
            place=1,
            prize=Prize.AIRPODS,
            user=create_user(username="winner", email="winner@example.com"),
            promocode=create_promocode("DRAWCODE"),
        )

        create_promocode("FRESHCOD")
        self.service.apply("FRESHCOD", self.user.id)
        result = {
            row["code"]: row for row in self.service.user_promocodes_list(self.user)
        }

        self.assertFalse(result["OLDPROMO"]["in_pool"])
        self.assertTrue(result["FRESHCOD"]["in_pool"])
