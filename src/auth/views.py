from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.tokens import default_token_generator
from django.shortcuts import redirect, render
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.http import require_GET
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from auth.exceptions import IncorrectPassword, UserDoesNotExists
from auth.forms import ForgotPasswordForm, ResetPasswordForm, SignUpForm
from auth.models import User
from auth.serializers import (
    ChangePasswordSerializer,
    NotifyOnPromocodeSerializer,
    UpdateProfileSerializer,
)
from auth.services import AuthService


def signup(request):
    if request.user.is_authenticated:
        return redirect("landing")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            AuthService().register(form.cleaned_data, request=request)
            return redirect("landing")
    else:
        form = SignUpForm()

    return render(request, "signup.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("landing")

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect("landing")
    else:
        form = AuthenticationForm(request)

    return render(request, "login.html", {"form": form})


def logout_view(request):
    if request.method == "POST":
        logout(request)
    return redirect("landing")


@require_GET
def confirm_email(request, uidb64, token):
    try:
        AuthService().confirm_email(uidb64, token, request)
        return redirect("landing")
    except Exception:
        return render(request, "confirm_email_invalid.html", status=400)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_notify_on_promocode(request):
    serializer = NotifyOnPromocodeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = AuthService().set_notify_on_promocode(
        request.user,
        serializer.validated_data["notify_on_promocode"],
    )
    return Response(
        {"ok": True, "notify_on_promocode": user.notify_on_promocode},
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_profile(request):
    serializer = UpdateProfileSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = AuthService().update_profile(
        request.user,
        first_name=serializer.validated_data.get("first_name", ""),
        last_name=serializer.validated_data.get("last_name", ""),
        middle_name=serializer.validated_data.get("middle_name", ""),
    )
    return Response(
        {
            "ok": True,
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "middle_name": user.middle_name or "",
            "full_name": user.get_full_name() or user.username,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    serializer = ChangePasswordSerializer(
        data=request.data,
        context={"user": request.user},
    )
    serializer.is_valid(raise_exception=True)

    try:
        AuthService().set_user_password(
            request.user,
            serializer.validated_data["old_password"],
            serializer.validated_data["new_password"],
        )
    except IncorrectPassword:
        return Response(
            {"detail": "Неверный текущий пароль"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except UserDoesNotExists:
        return Response(
            {"detail": "Пользователь не найден"},
            status=status.HTTP_404_NOT_FOUND,
        )

    update_session_auth_hash(request, request.user)
    return Response({"ok": True})


def forgot_password(request):
    if request.user.is_authenticated:
        return redirect("landing")

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
