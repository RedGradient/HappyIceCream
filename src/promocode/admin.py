from typing import Any

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.options import ModelAdmin
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import SafeString
from django.views.decorators.http import require_GET, require_POST

from config.tasks import (
    SESSION_PROMO_GEN_STARTED_AT,
    SESSION_PROMO_GEN_TASK_ID,
    generate_promocodes,
    promo_gen_task_status,
    request_promo_gen_cancel,
)
from promocode.exceptions import WinnerAlreadySelectedToday
from promocode.forms import ExcelFileForm, GeneratePromocodesForm, SeedTestDataForm
from promocode.models import DailyDraw, PromoActivation, PromoAttempt, Promocode
from promocode.services import (
    AnalyticsService,
    CabinetService,
    ExcelService,
    TestDataService,
    WinnerService,
)

DRAW_POOL_PAGE_SIZE = 50


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


@admin.register(PromoAttempt)
class PromoAttemptAdmin(ModelAdmin):
    list_display = (
        "id",
        "user",
        "attempted_code",
        "reason",
        "ip_address",
        "created_at",
    )
    list_filter = ("reason", "created_at")
    search_fields = ("attempted_code", "user__username", "user__email", "ip_address")
    ordering = ("-created_at",)
    readonly_fields = (
        "user",
        "attempted_code",
        "reason",
        "ip_address",
        "user_agent",
        "created_at",
    )
    raw_id_fields = ("user",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        return False


@admin.register(DailyDraw)
class DailyDrawAdmin(ModelAdmin):
    list_display = ("id", "date", "place", "prize", "user", "promocode", "created_at")
    list_filter = ("date", "place", "prize")
    ordering = ("-date", "place")
    readonly_fields = ("created_at",)
    raw_id_fields = ("user", "promocode")


def _winner_success_message(draw: DailyDraw) -> SafeString:
    user = draw.user
    promocode = draw.promocode
    prize_label = draw.get_prize_display() if draw.prize else "—"
    if user and promocode:
        fio = (
            " ".join(
                part
                for part in (user.last_name, user.first_name, user.middle_name)
                if part
            )
            or user.username
        )
        user_url = reverse("admin:user_auth_user_change", args=[user.pk])
        promo_url = reverse(
            "admin:promocode_promocode_change",
            args=[promocode.pk],
        )
        return format_html(
            '<a href="{}">{}</a>, email: {}, приз: {}, промокод: <a href="{}">«{}»</a>',
            user_url,
            fio,
            user.email,
            prize_label,
            promo_url,
            promocode.code,
        )
    return format_html(
        "user_id={}, приз: {}",
        draw.user_id,
        prize_label,
    )


@require_POST
def pick_random_winner_view(request: HttpRequest) -> HttpResponseRedirect:
    force = request.POST.get("force") == "1"
    send_email = request.POST.get("send_email") == "1"
    try:
        if force:
            WinnerService.clear_today_draw()

        winners = WinnerService().get_random_winner(notify=send_email)
        if not winners:
            messages.info(request, "Розыгрыш закрыт: сегодня без победителей.")
        else:
            joined = _winner_success_message(winners[0])
            for winner in winners[1:]:
                joined = format_html("{}; {}", joined, _winner_success_message(winner))
            messages.success(
                request,
                format_html("Победители выбраны: {}.", joined),
            )
    except WinnerAlreadySelectedToday:
        messages.warning(request, "Розыгрыш сегодня уже проведён.")
    except Exception as exc:
        messages.error(request, f"Ошибка при выборе победителя: {exc}")

    return redirect("admin:index")


@require_POST
def generate_promocodes_view(request: HttpRequest) -> HttpResponseRedirect:
    form = GeneratePromocodesForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            "Укажите целое число промокодов от 1 до 5 000 000.",
        )
        return redirect("admin:index")

    existing_id = request.session.get(SESSION_PROMO_GEN_TASK_ID)
    if existing_id:
        status = promo_gen_task_status(existing_id)
        if not status["done"]:
            messages.warning(
                request,
                "Генерация уже выполняется — дождитесь завершения.",
            )
            return redirect("admin:index")

    count = form.cleaned_data["count"]
    async_result = generate_promocodes.delay(count)
    request.session[SESSION_PROMO_GEN_TASK_ID] = async_result.id
    request.session[SESSION_PROMO_GEN_STARTED_AT] = timezone.now().isoformat()
    return redirect("admin:index")


@require_GET
def generate_promocodes_status_view(request: HttpRequest) -> JsonResponse:
    task_id = request.GET.get("task_id") or request.session.get(
        SESSION_PROMO_GEN_TASK_ID
    )
    if not task_id:
        return JsonResponse(
            {
                "task_id": None,
                "state": "ABSENT",
                "done": True,
                "success": False,
                "cancelled": False,
                "cancel_requested": False,
                "percent": 0,
                "current": 0,
                "total": 0,
                "error": None,
                "created": None,
                "requested": None,
                "started_at": None,
                "elapsed_seconds": None,
            }
        )

    status = promo_gen_task_status(
        task_id,
        started_at=request.session.get(SESSION_PROMO_GEN_STARTED_AT),
    )
    if status["done"]:
        request.session.pop(SESSION_PROMO_GEN_TASK_ID, None)
        request.session.pop(SESSION_PROMO_GEN_STARTED_AT, None)
    return JsonResponse(status)


@require_POST
def generate_promocodes_cancel_view(request: HttpRequest) -> JsonResponse:
    task_id = request.POST.get("task_id") or request.session.get(
        SESSION_PROMO_GEN_TASK_ID
    )
    if not task_id:
        return JsonResponse(
            {"ok": False, "error": "Нет активной генерации."},
            status=400,
        )

    status = promo_gen_task_status(
        task_id,
        started_at=request.session.get(SESSION_PROMO_GEN_STARTED_AT),
    )
    if status["done"]:
        request.session.pop(SESSION_PROMO_GEN_TASK_ID, None)
        request.session.pop(SESSION_PROMO_GEN_STARTED_AT, None)
        return JsonResponse(
            {"ok": False, "error": "Генерация уже завершена."},
            status=400,
        )

    request_promo_gen_cancel(task_id)
    return JsonResponse({"ok": True, "task_id": task_id})


@require_POST
def load_from_excel(request: HttpRequest) -> HttpResponseRedirect:
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


@require_POST
def seed_test_data_view(request: HttpRequest) -> HttpResponseRedirect:
    if not getattr(settings, "ALLOW_TEST_SEED", False):
        messages.error(request, "Создание тестовых данных отключено.")
        return redirect("admin:index")

    form = SeedTestDataForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Укажите число участников от 1 до 100.")
        return redirect("admin:index")

    try:
        result = TestDataService.seed_participants(form.cleaned_data["count"])
    except Exception as exc:
        messages.error(request, f"Не удалось создать тестовые данные: {exc}")
        return redirect("admin:index")

    messages.success(
        request,
        (
            f"Создано участников: {result['users']}, "
            f"промокодов: {result['promocodes']}, "
            f"активаций: {result['activations']}. "
            f"Пароль для входа: {result['password']}"
        ),
    )
    return redirect("admin:index")


def metrics_view(request: HttpRequest) -> HttpResponse:
    stats = AnalyticsService.summary()
    context = {
        **admin.site.each_context(request),
        "title": "Метрики",
        "stats": stats,
    }
    return render(request, "admin/metrics.html", context)


@require_GET
def draw_pool_view(request: HttpRequest) -> HttpResponse:
    qs, activated_from = WinnerService.current_pool_queryset()
    paginator = Paginator(qs, DRAW_POOL_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    context = {
        **admin.site.each_context(request),
        "title": "Пул следующего розыгрыша",
        "page_obj": page_obj,
        "pool": {
            "count": paginator.count,
            "unique_users": qs.values("user_id").distinct().count(),
            "activated_from": activated_from,
            "next_draw_at": CabinetService.next_draw_at(),
        },
        "activated_from": activated_from,
    }
    return render(request, "admin/draw_pool.html", context)


@require_GET
def metrics_export_excel_view(request: HttpRequest) -> HttpResponse:
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
_original_index = admin.site.index


def _admin_index(
    request: HttpRequest, extra_context: dict[str, Any] | None = None
) -> HttpResponse:
    extra_context = extra_context or {}
    today_draws = list(
        DailyDraw.objects.filter(date=timezone.localdate())
        .select_related("user", "promocode")
        .order_by("place")
    )
    extra_context["today_draws"] = today_draws
    extra_context["today_draw"] = bool(today_draws)
    extra_context["draw_pool"] = WinnerService.current_pool_summary()
    extra_context["allow_test_seed"] = getattr(settings, "ALLOW_TEST_SEED", False)

    task_id = request.session.get(SESSION_PROMO_GEN_TASK_ID)
    promo_gen = None
    promo_gen_result = None
    if task_id:
        promo_gen = promo_gen_task_status(
            task_id,
            started_at=request.session.get(SESSION_PROMO_GEN_STARTED_AT),
        )
        if promo_gen["done"]:
            request.session.pop(SESSION_PROMO_GEN_TASK_ID, None)
            request.session.pop(SESSION_PROMO_GEN_STARTED_AT, None)
            promo_gen_result = promo_gen
            promo_gen = None
    extra_context["promo_gen_task"] = promo_gen
    extra_context["promo_gen_result"] = promo_gen_result

    return _original_index(request, extra_context)


def _get_urls() -> list:
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
            "draw-pool/",
            admin.site.admin_view(draw_pool_view),
            name="draw_pool",
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
            "generate-promocodes/status/",
            admin.site.admin_view(generate_promocodes_status_view),
            name="generate_promocodes_status",
        ),
        path(
            "generate-promocodes/cancel/",
            admin.site.admin_view(generate_promocodes_cancel_view),
            name="generate_promocodes_cancel",
        ),
        path(
            "load-from-excel/",
            admin.site.admin_view(load_from_excel),
            name="load_from_excel",
        ),
        path(
            "seed-test-data/",
            admin.site.admin_view(seed_test_data_view),
            name="seed_test_data",
        ),
    ]
    return custom_urls + _original_get_urls()


admin.site.get_urls = _get_urls
admin.site.index = _admin_index
