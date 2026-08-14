from typing import ClassVar

from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.tokens import default_token_generator
from django.shortcuts import redirect, render
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.http import require_GET
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from auth.exceptions import IncorrectPassword
from auth.forms import (
    EmailAuthenticationForm,
    ForgotPasswordForm,
    ResetPasswordForm,
    SignUpForm,
)
from auth.models import User
from auth.serializers import AccountSerializer, ChangePasswordSerializer
from auth.services import AuthService


def signup(request):
    if request.user.is_authenticated:
        return redirect("account")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            AuthService().register(form.cleaned_data, request=request)
            return redirect("login")
    else:
        form = SignUpForm()

    return render(request, "signup.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("account")

    if request.method == "POST":
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect("account")
    else:
        form = EmailAuthenticationForm(request)

    return render(request, "login.html", {"form": form})


def logout_view(request):
    if request.method == "POST":
        logout(request)
    return redirect("login")


@require_GET
def confirm_email(request, uidb64, token):
    try:
        AuthService().confirm_email(uidb64, token, request)
        return redirect("account")
    except Exception:
        return render(request, "confirm_email_invalid.html", status=400)


class AccountView(RetrieveUpdateAPIView):
    """
    GET /api/account/ — текущий профиль
    PATCH /api/account/ — частичное обновление личных данных
    """

    authentication_classes: ClassVar[list] = [SessionAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    serializer_class = AccountSerializer
    http_method_names: ClassVar[list[str]] = ["get", "put", "patch", "head", "options"]

    def get_object(self) -> User:
        return self.request.user


class AccountPasswordView(APIView):
    """POST /api/account/password/ — смена пароля."""

    authentication_classes: ClassVar[list] = [SessionAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = AuthService().set_user_password(
                request.user,
                serializer.validated_data["old_password"],
                serializer.validated_data["new_password"],
            )
        except IncorrectPassword:
            return Response(
                {"detail": "Неверный текущий пароль"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        update_session_auth_hash(request, user)
        return Response({"ok": True})


def forgot_password(request):
    if request.user.is_authenticated:
        return redirect("account")

    if request.method == "POST":
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            AuthService().send_password_reset(form.cleaned_data["email"], request)
            return render(request, "forgot_password_done.html")
    else:
        form = ForgotPasswordForm()

    return render(request, "forgot_password.html", {"form": form})


def password_reset_confirm(request, uidb64: str, token: str):
    # Получаем пользователя
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, User.DoesNotExist):
        return render(request, "confirm_email_invalid.html", status=400)

    # Проверка корректности токена (срок действия, актуальность)
    if not default_token_generator.check_token(user, token):
        return render(request, "confirm_email_invalid.html", status=400)

    if request.method == "POST":
        form = ResetPasswordForm(request.POST, user=user)
        if form.is_valid():
            AuthService().reset_password(user, form.cleaned_data["password"])
            return render(request, "reset_password_done.html")
    else:
        form = ResetPasswordForm(user=user)

    return render(request, "reset_password.html", {"form": form})
