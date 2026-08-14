from datetime import date

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from auth.models import User


class AccountApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="john_doe",
            email="john@example.com",
            password="old-password-1",
            first_name="John",
            last_name="Doe",
        )
        self.client.force_authenticate(user=self.user)

    def test_get_account(self):
        response = self.client.get(reverse("api_account"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "john@example.com")
        self.assertEqual(response.data["first_name"], "John")
        self.assertEqual(response.data["full_name"], "John Doe")

    def test_patch_account_personal_data(self):
        response = self.client.patch(
            reverse("api_account"),
            {
                "first_name": "Ivan",
                "last_name": "Petrov",
                "middle_name": "Ivanovich",
                "birth_date": "1990-05-01",
                "telephone_number": "+79001112233",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Ivan")
        self.assertEqual(self.user.last_name, "Petrov")
        self.assertEqual(self.user.middle_name, "Ivanovich")
        self.assertEqual(self.user.birth_date, date(1990, 5, 1))
        self.assertEqual(self.user.telephone_number, "+79001112233")
        self.assertEqual(response.data["full_name"], "Ivan Petrov")

    def test_patch_account_notify_only(self):
        response = self.client.patch(
            reverse("api_account"),
            {"notify_on_promocode": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertFalse(self.user.notify_on_promocode)
        self.assertEqual(self.user.first_name, "John")

    def test_change_password(self):
        response = self.client.post(
            reverse("api_account_password"),
            {
                "old_password": "old-password-1",
                "new_password": "new-password-1",
                "new_password_confirm": "new-password-1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-password-1"))

    def test_change_password_keeps_session(self):
        self.client.logout()
        self.assertTrue(
            self.client.login(username="john_doe", password="old-password-1")
        )
        response = self.client.post(
            reverse("api_account_password"),
            {
                "old_password": "old-password-1",
                "new_password": "new-password-1",
                "new_password_confirm": "new-password-1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        me = self.client.get(reverse("api_account"))
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertEqual(me.data["email"], "john@example.com")

    def test_change_password_wrong_old(self):
        response = self.client.post(
            reverse("api_account_password"),
            {
                "old_password": "wrong-password",
                "new_password": "new-password-1",
                "new_password_confirm": "new-password-1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_account_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("api_account"))
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
