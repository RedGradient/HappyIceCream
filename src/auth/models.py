from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    id = models.BigAutoField(primary_key=True)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, null=True, blank=True)
    last_name = models.CharField(max_length=150, null=True, blank=True)
    middle_name = models.CharField(max_length=150, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    telephone_number = models.CharField(max_length=32, null=True, blank=True)
    email_confirmed = models.BooleanField(default=False)
    notify_on_promocode = models.BooleanField(default=True)
    winner = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users"

    def __str__(self) -> str:
        return self.username
