from django.urls import path

from auth.views import (
    confirm_email,
    login_view,
    logout_view,
    signup,
    update_notify_on_promocode,
)

urlpatterns = [
    path("signup/", signup, name="signup"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("confirm/<uidb64>/<token>/", confirm_email, name="confirm_email"),
    path(
        "notify-on-promocode/",
        update_notify_on_promocode,
        name="notify_on_promocode",
    ),
]
