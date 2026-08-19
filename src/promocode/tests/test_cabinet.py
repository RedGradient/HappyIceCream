from django.test import TestCase

from promocode.models import PromoActivation
from promocode.services.cabinet import CabinetService
from promocode.tests.helpers import create_promocode, create_user


class CabinetServiceTests(TestCase):
    def setUp(self):
        self.user = create_user(
            first_name="John",
            last_name="Doe",
            email_confirmed=True,
        )

    def test_participation_counts_codes_in_current_pool(self):
        promo = create_promocode("ABCDEFGH")
        PromoActivation.objects.create(user=self.user, promocode=promo)

        data = CabinetService().participation(self.user)
        self.assertEqual(data["codes_count"], 1)
        self.assertTrue(data["eligible"])
        self.assertFalse(data["already_won"])
        self.assertEqual(data["collection_until"], data["next_draw_at"])

    def test_participation_zero_if_already_won(self):
        self.user.winner = True
        self.user.save(update_fields=["winner"])
        promo = create_promocode("ABCDEFGH")
        PromoActivation.objects.create(user=self.user, promocode=promo)

        data = CabinetService().participation(self.user)
        self.assertEqual(data["codes_count"], 0)
        self.assertTrue(data["already_won"])

    def test_checklist(self):
        checklist = CabinetService.profile_checklist(self.user)
        self.assertTrue(checklist["complete"])

        incomplete = create_user(
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
