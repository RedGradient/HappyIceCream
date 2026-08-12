from django.contrib.auth import login
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from auth.exceptions import IncorrectPassword, UserDoesNotExists
from auth.models import User


def _build_confirm_url(user: User, request) -> str:
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse("confirm_email", kwargs={"uidb64": uidb64, "token": token})
    return request.build_absolute_uri(path)


class EmailService:
    def send_confirm_email(self, user: User, request):
        confirm_url = _build_confirm_url(user, request)
        send_mail(
            subject="Подтвердите регистрацию",
            message=f"Перейдите по ссылке: {confirm_url}",
            from_email=None,
            recipient_list=[user.email],
        )


class AuthService:
    def register(self, data, request) -> User:
        user = User(
            username=data["username"],
            email=data["email"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            middle_name=data["middle_name"],
        )
        user.set_password(data["password"])
        user.email_confirmed = False
        user.save()

        # Отправка email для подтверждения почты
        EmailService().send_confirm_email(user, request)

        return user

    def confirm_email(self, uidb64, token, request):
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist) as exc:
            raise ValueError("Invalid confirmation link") from exc

        if not default_token_generator.check_token(user, token):
            raise ValueError("Invalid or expired token")

        user.email_confirmed = True
        user.save(update_fields=["email_confirmed"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    def set_notify_on_promocode(self, user: User, enabled: bool) -> User:
        user.notify_on_promocode = enabled
        user.save(update_fields=["notify_on_promocode"])
        return user

    def set_user_password(self, user: User, old_password: str, new_password: str):
        try:
            user = User.objects.get(pk=user.id)
            if not user.check_password(old_password):
                raise IncorrectPassword()
            user.set_password(new_password)
            user.save(update_fields=["password"])
        except User.DoesNotExist as exc:
            raise UserDoesNotExists() from exc
