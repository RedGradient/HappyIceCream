from django.test import TestCase

from auth.models import User
from promocode.models import PromoActivation, Promocode


class TestDataSeedTests(TestCase):
    def test_seed_participants_creates_full_chain(self):
        from promocode.services.testdata import TestDataService

        result = TestDataService.seed_participants(3)
        self.assertEqual(result["users"], 3)
        self.assertEqual(result["promocodes"], 3)
        self.assertEqual(result["activations"], 3)
        self.assertEqual(User.objects.filter(email_confirmed=True).count(), 3)
        self.assertEqual(PromoActivation.objects.count(), 3)
        self.assertEqual(Promocode.objects.filter(is_taken=True).count(), 3)
        user = User.objects.get(last_name="Юзер1")
        self.assertTrue(user.check_password("testpass123"))
        self.assertTrue(user.email_confirmed)
        self.assertFalse(user.winner)

    def test_seed_admin_endpoint(self):
        from django.contrib.auth import get_user_model

        admin_user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="admin-pass-1",
        )
        self.client.force_login(admin_user)
        with self.settings(ALLOW_TEST_SEED=True):
            response = self.client.post("/admin/seed-test-data/", {"count": 2})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PromoActivation.objects.count(), 2)

    def test_seed_disabled_when_flag_off(self):
        from django.contrib.auth import get_user_model

        admin_user = get_user_model().objects.create_superuser(
            username="admin2",
            email="admin2@example.com",
            password="admin-pass-1",
        )
        self.client.force_login(admin_user)
        with self.settings(ALLOW_TEST_SEED=False):
            response = self.client.post("/admin/seed-test-data/", {"count": 1})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PromoActivation.objects.count(), 0)
