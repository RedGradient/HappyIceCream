from django.urls import path

from auth.views import (
    change_password,
    confirm_email,
    forgot_password,
    login_view,
    logout_view,
    password_reset_confirm,
    signup,
    update_notify_on_promocode,
    update_profile,
)

urlpatterns = [
    path("signup/", signup, name="signup"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("confirm/<uidb64>/<token>/", confirm_email, name="confirm_email"),
    path("profile/", update_profile, name="update_profile"),
    path("password/change/", change_password, name="change_password"),
    path("password/forgot/", forgot_password, name="forgot_password"),
    path(
        "password/reset/<uidb64>/<token>/",
        password_reset_confirm,
        name="password_reset_confirm",
    ),
    path(
        "notify-on-promocode/",
        update_notify_on_promocode,
        name="notify_on_promocode",
    ),
]
