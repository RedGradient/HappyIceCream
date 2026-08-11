from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from promocode.exceptions import PromocodeAlreadyUsed, PromocodeDoesNotExists
from promocode.serializers import PromoCodeSerializer
from promocode.services import PromoCodeService


def landing(request):
    return render(request, "landing.html")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def apply_promocode(request):
    # Валидация промокода
    code_serializer = PromoCodeSerializer(data=request.data)
    code_serializer.is_valid(raise_exception=True)

    try:
        code = code_serializer.validated_data["code"]
        # Применяем промокод
        PromoCodeService().apply(code, request.user.id)
    except PromocodeDoesNotExists:
        return Response(
            {"detail": "Промокод не найден"},
            status=status.HTTP_404_NOT_FOUND,
        )
    except PromocodeAlreadyUsed:
        return Response(
            {"detail": "Промокод уже использован"},
            status=status.HTTP_409_CONFLICT,
        )

    return Response({"ok": True})
