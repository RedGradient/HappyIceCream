from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from promocode.tests.helpers import create_user


class PromoCooldownTests(TestCase):
    def setUp(self):
        self.user = create_user(
            first_name="John",
            last_name="Doe",
            email_confirmed=True,
        )
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

        self.assertIn("cooldown_until", response.json())

        locked = self.client.post(
            "/promocode",
            {"code": "WRONGCOD"},
            format="json",
        )
        self.assertEqual(locked.status_code, 429)
        self.assertIn("cooldown_until", locked.json())
        self.assertIn("Повторите через", locked.json()["detail"])

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
