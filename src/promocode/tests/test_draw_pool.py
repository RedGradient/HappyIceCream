from django.test import TestCase

from promocode.models import PromoActivation
from promocode.tests.helpers import create_promocode, create_user


class DrawPoolTests(TestCase):
    def setUp(self):
        self.user = create_user(
            username="pool_user",
            email="pool@example.com",
            first_name="Ann",
            last_name="Lee",
            email_confirmed=True,
            winner=False,
        )

    def test_current_pool_includes_eligible_activations(self):
        from promocode.services import WinnerService

        promo = create_promocode("POOLCODE")
        PromoActivation.objects.create(user=self.user, promocode=promo)

        qs, activated_from = WinnerService.current_pool_queryset()
        self.assertIsNotNone(activated_from)
        self.assertEqual(qs.count(), 1)
        summary = WinnerService.current_pool_summary()
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["unique_users"], 1)

    def test_current_pool_excludes_winners(self):
        from promocode.services import WinnerService

        self.user.winner = True
        self.user.save(update_fields=["winner"])
        promo = create_promocode("POOLCODE")
        PromoActivation.objects.create(user=self.user, promocode=promo)

        qs, _ = WinnerService.current_pool_queryset()
        self.assertEqual(qs.count(), 0)

    def test_draw_pool_admin_page(self):
        from django.contrib.auth import get_user_model

        admin_user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="admin-pass-1",
        )
        self.client.force_login(admin_user)
        response = self.client.get("/admin/draw-pool/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Пул следующего розыгрыша")
