from django.urls import path

from auth.views import confirm_email, login_view, logout_view, signup

urlpatterns = [
    path("signup/", signup, name="signup"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("confirm/<uidb64>/<token>/", confirm_email, name="confirm_email"),
]
