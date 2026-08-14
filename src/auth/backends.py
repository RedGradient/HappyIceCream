from django.contrib.auth.backends import ModelBackend

from auth.models import User


class EmailBackend(ModelBackend):
    """Аутентификация по email (поле формы по-прежнему называется username)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if not username or password is None:
            return None

        try:
            user = User.objects.get(email__iexact=username)
        except User.DoesNotExist:
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
