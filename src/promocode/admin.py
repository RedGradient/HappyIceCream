from django.contrib import admin, messages
from django.contrib.admin.options import ModelAdmin
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path
from django.views.decorators.http import require_GET, require_POST

from auth.models import User
from config.tasks import generate_promocodes
from promocode.exceptions import WinnerAlreadySelectedToday
from promocode.forms import ExcelFileForm, GeneratePromocodesForm
from promocode.models import DailyDraw, PromoActivation, Promocode
from promocode.services import AnalyticsService, ExcelService, WinnerService


@admin.register(Promocode)
class PromoCodeAdmin(ModelAdmin):
    list_display = ("id", "code", "is_taken", "created_at")
    list_filter = ("is_taken", "created_at")
    search_fields = ("code",)
    ordering = ("-id",)


@admin.register(PromoActivation)
class UserPromocodeAdmin(ModelAdmin):
    list_display = ("id", "user", "promocode", "is_won", "won_on", "created_at")
    list_filter = ("is_won", "won_on", "created_at")
    search_fields = ("user__username", "user__email", "promocode__code")
    ordering = ("-id",)
    raw_id_fields = ("user", "promocode")


@admin.register(DailyDraw)
class DailyDrawAdmin(ModelAdmin):
    list_display = ("id", "date", "user", "promocode", "created_at")
    list_filter = ("date",)
    ordering = ("-date",)
    readonly_fields = ("created_at",)
    raw_id_fields = ("user", "promocode")


@require_POST
def pick_random_winner_view(request):
    try:
        winner = WinnerService().get_random_winner()
        if winner is None:
            messages.info(request, "Розыгрыш закрыт: сегодня без победителя.")
        else:
            user = User.objects.filter(pk=winner.user_id).first()
            name = user.get_full_name() or user.username if user else winner.user_id
            messages.success(
                request,
                f"Победитель выбран: {name} "
                f"(promocode_id={winner.promocode_id}, дата={winner.won_on}).",
            )
    except WinnerAlreadySelectedToday:
        messages.warning(request, "Розыгрыш сегодня уже проведён.")
    except Exception as exc:
        messages.error(request, f"Ошибка при выборе победителя: {exc}")

    return redirect("admin:index")


@require_POST
def generate_promocodes_view(request):
    form = GeneratePromocodesForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            "Укажите целое число промокодов от 1 до 5 000 000.",
        )
        return redirect("admin:index")

    count = form.cleaned_data["count"]
    generate_promocodes.delay(count)
    messages.success(
        request,
        f"Запущена генерация {count:,} промокодов (задача в Celery).",
    )
    return redirect("admin:index")


@require_POST
def load_from_excel(request):
    form = ExcelFileForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Выберите файл Excel (.xlsx или .xls).")
        return redirect("admin:index")

    upload = form.cleaned_data["file"]
    try:
        created = ExcelService().load_from_excel(upload)
    except Exception as exc:
        messages.error(request, f"Не удалось импортировать файл: {exc}")
        return redirect("admin:index")

    messages.success(request, f"Импортировано промокодов: {created}.")
    return redirect("admin:index")


def metrics_view(request):
    stats = AnalyticsService.summary()
    context = {
        **admin.site.each_context(request),
        "title": "Метрики",
        "stats": stats,
    }
    return render(request, "admin/metrics.html", context)


@require_GET
def metrics_export_excel_view(request):
    content, filename = AnalyticsService.export_analytics_as_excel()
    response = HttpResponse(
        content,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


_original_get_urls = admin.site.get_urls


def _get_urls():
    custom_urls = [
        path(
            "metrics/",
            admin.site.admin_view(metrics_view),
            name="metrics",
        ),
        path(
            "metrics/export/",
            admin.site.admin_view(metrics_export_excel_view),
            name="metrics_export_excel",
        ),
        path(
            "pick-random-winner/",
            admin.site.admin_view(pick_random_winner_view),
            name="pick_random_winner",
        ),
        path(
            "generate-promocodes/",
            admin.site.admin_view(generate_promocodes_view),
            name="generate_promocodes",
        ),
        path(
            "load-from-excel/",
            admin.site.admin_view(load_from_excel),
            name="load_from_excel",
        ),
    ]
    return custom_urls + _original_get_urls()


admin.site.get_urls = _get_urls
