from django.contrib.auth import login
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from auth.exceptions import IncorrectPassword
from auth.models import User
from auth.tokens import email_confirm_token_generator


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

        self._send_confirm_email(user, request)

        return user

    @staticmethod
    def confirm_email(uidb64, token, request):
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist) as exc:
            raise ValueError("Invalid confirmation link") from exc

        if not email_confirm_token_generator.check_token(user, token):
            raise ValueError("Invalid or expired token")

        user.email_confirmed = True
        user.save(update_fields=["email_confirmed"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    @staticmethod
    def set_notify_on_promocode(user: User, enabled: bool) -> User:
        user.notify_on_promocode = enabled
        user.save(update_fields=["notify_on_promocode"])
        return user

    @staticmethod
    def update_profile(
        user: User,
        *,
        first_name: str | None = "",
        last_name: str | None = "",
        middle_name: str | None = "",
        birth_date=None,
        telephone_number: str | None = "",
        notify_on_promocode: bool | None = None,
    ) -> User:
        user.first_name = (first_name or "").strip() or None
        user.last_name = (last_name or "").strip() or None
        user.middle_name = (middle_name or "").strip() or None
        user.birth_date = birth_date
        user.telephone_number = (telephone_number or "").strip() or None
        update_fields = [
            "first_name",
            "last_name",
            "middle_name",
            "birth_date",
            "telephone_number",
        ]
        if notify_on_promocode is not None:
            user.notify_on_promocode = notify_on_promocode
            update_fields.append("notify_on_promocode")
        user.save(update_fields=update_fields)
        return user

    @staticmethod
    def set_user_password(user: User, old_password: str, new_password: str) -> User:
        if not user.check_password(old_password):
            raise IncorrectPassword()
        user.set_password(new_password)
        user.save(update_fields=["password"])
        return user

    @staticmethod
    def reset_password(user: User, new_password: str) -> User:
        user.set_password(new_password)
        user.save(update_fields=["password"])
        return user

    @staticmethod
    def send_password_reset(email: str, request):
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            return

        reset_url = AuthService._build_password_reset_url(user, request)
        send_mail(
            subject="Сброс пароля — Happy Ice Cream",
            message=(
                f"Перейдите по ссылке для смены пароля:\n{reset_url}\n\n"
                "Если это были не вы, проигнорируйте письмо."
            ),
            from_email=None,
            recipient_list=[user.email],
        )

    @staticmethod
    def resend_confirm_email(user: User, request) -> None:
        if user.email_confirmed:
            raise ValueError("Email уже подтверждён")
        AuthService._send_confirm_email(user, request)

    @staticmethod
    def _send_confirm_email(user: User, request):
        confirm_url = AuthService._build_confirm_url(user, request)
        send_mail(
            subject="Подтвердите регистрацию",
            message=f"Перейдите по ссылке: {confirm_url}",
            from_email=None,
            recipient_list=[user.email],
        )

    @staticmethod
    def _build_confirm_url(user: User, request) -> str:
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_confirm_token_generator.make_token(user)
        path = reverse("confirm_email", kwargs={"uidb64": uidb64, "token": token})
        return request.build_absolute_uri(path)

    @staticmethod
    def _build_password_reset_url(user: User, request) -> str:
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        path = reverse(
            "password_reset_confirm",
            kwargs={"uidb64": uidb64, "token": token},
        )
        return request.build_absolute_uri(path)
