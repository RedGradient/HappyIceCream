from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from promocode.serializers import PromoCodeSerializer
from promocode.services import PromoCodeService


def landing(request):
    return render(request, "landing.html")


@api_view(["POST"])
def promo(request):
    code_serializer = PromoCodeSerializer(data=request.data)
    code_serializer.is_valid(raise_exception=True)

    code = code_serializer.validated_data["code"]
    is_valid = PromoCodeService().check_code(code)

    if not is_valid:
        return Response(
            {"detail": "Промокод не найден"},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response({"ok": True})
