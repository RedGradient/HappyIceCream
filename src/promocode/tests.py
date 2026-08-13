from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from auth.models import User
from promocode.exceptions import PromocodeAlreadyUsed, PromocodeDoesNotExist
from promocode.models import Promocode, UserPromocode
from promocode.services import PromoCodeService


@patch.object(PromoCodeService, "_notify_on_promocode")
class PromocodeServiceTests(TestCase):
    def setUp(self):
        self.service = PromoCodeService()
        # Создаем пользователя
        self.user = User.objects.create(
            username="john_doe",
            email="john@example.com",
            notify_on_promocode=True,
        )

    def _create_promocode(self, code: str) -> Promocode:
        return Promocode.objects.create(
            code=code,
            is_taken=False,
            is_drawn=False,
        )

    def test_apply_ok(self, notify_mock):
        # Создаем promocode в БД
        promocode = self._create_promocode("ABCDEFGH")

        result = self.service.apply(promocode.code, self.user.id)

        user_promocode = UserPromocode.objects.get(user=self.user, promocode=promocode)
        self.assertEqual(user_promocode.user, result.user)
        self.assertEqual(user_promocode.promocode, result.promocode)
        self.assertEqual(user_promocode.created_at, result.created_at)
        self.assertIsNone(user_promocode.won_on)
        self.assertFalse(user_promocode.is_won)

        promocode.refresh_from_db()
        self.assertTrue(promocode.is_taken)
        self.assertFalse(promocode.is_drawn)

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
        promocode = self._create_promocode("TAKENABC")
        # Пользователь 1 забирает промокод
        self.service.apply(promocode.code, user_1.id)

        # Создаем пользователя 2, которого ждет неприятный сюрприз
        user_2 = User.objects.create(
            username="alice",
            email="alice@example.com",
            notify_on_promocode=True,
        )
        # Пользователь 2 применяет промокод и получает ошибку
        with self.assertRaises(PromocodeAlreadyUsed):
            self.service.apply(promocode.code, user_2.id)

        self.assertEqual(notify_mock.call_count, 1)

    def test_user_promocodes_list(self, notify_mock):
        # Создаем и применяем промокоды
        codes = ["AAAAAAAA", "BBBBBBBB", "CCCCCCCC", "12345678", "87654321"]
        base_time = timezone.now()
        for index, code in enumerate(codes):
            self._create_promocode(code)
            user_promocode = self.service.apply(code, self.user.id)
            # Фиксируем created_at, чтобы порядок в списке был стабильным
            UserPromocode.objects.filter(pk=user_promocode.pk).update(
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
