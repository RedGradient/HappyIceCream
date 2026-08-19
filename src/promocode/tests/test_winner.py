from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from promocode.exceptions import WinnerAlreadySelectedToday
from promocode.models import DailyDraw, PromoActivation
from promocode.services.winner import DAILY_PRIZES, WinnerService
from promocode.tests.helpers import create_promocode, create_user


class WinnerServiceTests(TestCase):
    @patch.object(WinnerService, "_notify_winner")
    def test_get_random_winner_ok(self, notify_mock):
        service = WinnerService()
        today = timezone.localdate()

        user1 = create_user(username="alice", email="alice@example.com")
        user2 = create_user(username="bob", email="bob@example.com")
        promo1 = create_promocode("ABCDEFGH")
        promo1.is_taken = True
        promo1.save(update_fields=["is_taken"])
        promo2 = create_promocode("HGFEEDCB")
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

        user = create_user()
        user.winner = True
        user.save(update_fields=["winner"])
        old_promo = create_promocode("AAAAAAAA")
        old_promo.is_taken = True
        old_promo.save(update_fields=["is_taken"])
        PromoActivation.objects.create(
            user=user,
            promocode=old_promo,
            is_won=True,
            won_on=yesterday,
            created_at=timezone.now() - timedelta(days=2),
        )

        candidate = create_promocode("BBBBBBBB")
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

        user = create_user()
        promocode = create_promocode("ABCDEFGH")
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

    @patch("promocode.services.winner.send_mail", side_effect=OSError("smtp down"))
    def test_get_random_winner_succeeds_if_email_fails(self, send_mail_mock):
        service = WinnerService()
        today = timezone.localdate()

        user = create_user(email="winner@example.com")
        promocode = create_promocode("ABCDEFGH")
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
        self.assertEqual(DailyDraw.objects.filter(date=today).count(), 2)
        send_mail_mock.assert_called()

    @patch.object(WinnerService, "_notify_winner")
    def test_clear_today_draw_allows_redo(self, notify_mock):
        service = WinnerService()
        today = timezone.localdate()

        user = create_user()
        promocode = create_promocode("ABCDEFGH")
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
