from django.test import TestCase
from rest_framework.test import APIClient

from promocode.models import PromoActivation, PromoAttempt, PromoAttemptReason
from promocode.tests.helpers import create_promocode, create_user


class PromoAttemptLoggingTests(TestCase):
    def setUp(self):
        self.user = create_user(
            first_name="John",
            last_name="Doe",
            email_confirmed=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_logs_not_found_attempt(self):
        response = self.client.post(
            "/promocode",
            {"code": "WRONGCOD"},
            format="json",
            HTTP_USER_AGENT="TestAgent/1.0",
        )
        self.assertEqual(response.status_code, 404)
        attempt = PromoAttempt.objects.get()
        self.assertEqual(attempt.user_id, self.user.id)
        self.assertEqual(attempt.attempted_code, "WRONGCOD")
        self.assertEqual(attempt.reason, PromoAttemptReason.NOT_FOUND)
        self.assertEqual(attempt.user_agent, "TestAgent/1.0")
        self.assertTrue(attempt.ip_address)

    def test_logs_already_used_attempt(self):
        promo = create_promocode("USEDCODE")
        other = create_user(username="other", email="other@example.com")
        PromoActivation.objects.create(user=other, promocode=promo)
        promo.is_taken = True
        promo.save(update_fields=["is_taken"])

        response = self.client.post(
            "/promocode",
            {"code": "USEDCODE"},
            format="json",
            HTTP_USER_AGENT="Mozilla/5.0",
        )
        self.assertEqual(response.status_code, 409)
        attempt = PromoAttempt.objects.get()
        self.assertEqual(attempt.reason, PromoAttemptReason.ALREADY_USED)
        self.assertEqual(attempt.attempted_code, "USEDCODE")
        self.assertEqual(attempt.user_agent, "Mozilla/5.0")
