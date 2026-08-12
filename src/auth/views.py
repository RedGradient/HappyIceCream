from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from auth.forms import SignUpForm
from auth.serializers import NotifyOnPromocodeSerializer
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
