from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailConfirmTokenGenerator(PasswordResetTokenGenerator):
    """Токен подтверждения email"""

    def _make_hash_value(self, user, timestamp) -> str:
        email = getattr(user, "email", "") or ""
        confirmed = getattr(user, "email_confirmed", False)
        return f"{user.pk}{email}{confirmed}{timestamp}"


email_confirm_token_generator = EmailConfirmTokenGenerator()
