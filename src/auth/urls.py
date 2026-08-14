from django.urls import path

from auth.views import (
    AccountPasswordView,
    AccountView,
    ResendConfirmEmailView,
    confirm_email,
    forgot_password,
    login_view,
    logout_view,
    password_reset_confirm,
    signup,
)

urlpatterns = [
    path("signup/", signup, name="signup"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("confirm/<uidb64>/<token>/", confirm_email, name="confirm_email"),
    path("api/account/", AccountView.as_view(), name="api_account"),
    path(
        "api/account/password/",
        AccountPasswordView.as_view(),
        name="api_account_password",
    ),
    path(
        "api/account/resend-confirm-email/",
        ResendConfirmEmailView.as_view(),
        name="api_account_resend_confirm_email",
    ),
    path("password/forgot/", forgot_password, name="forgot_password"),
    path(
        "password/reset/<uidb64>/<token>/",
        password_reset_confirm,
        name="password_reset_confirm",
    ),
]
