import logging
from datetime import datetime

import redis
from celery import shared_task
from celery.result import AsyncResult
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from promocode.exceptions import WinnerAlreadySelectedToday
from promocode.services.promocode import PromoCodeService
from promocode.services.winner import WinnerService

logger = logging.getLogger(__name__)

SESSION_PROMO_GEN_TASK_ID = "promo_gen_task_id"
SESSION_PROMO_GEN_STARTED_AT = "promo_gen_started_at"
PROMO_GEN_CANCEL_KEY = "promo_gen:cancel:{task_id}"
PROMO_GEN_CANCEL_TTL_SECONDS = 60 * 60 * 24


def _promo_gen_redis() -> redis.Redis:
    url = settings.CELERY_RESULT_BACKEND or settings.CELERY_BROKER_URL
    return redis.Redis.from_url(url, decode_responses=True)


def _cancel_key(task_id: str) -> str:
    return PROMO_GEN_CANCEL_KEY.format(task_id=task_id)


def clear_promo_gen_cancel(task_id: str) -> None:
    _promo_gen_redis().delete(_cancel_key(task_id))


def request_promo_gen_cancel(task_id: str) -> None:
    _promo_gen_redis().setex(
        _cancel_key(task_id),
        PROMO_GEN_CANCEL_TTL_SECONDS,
        "1",
    )


def is_promo_gen_cancelled(task_id: str) -> bool:
    return bool(_promo_gen_redis().get(_cancel_key(task_id)))


@shared_task(name="select_random_winner")
def select_random_winner():
    try:
        winners = WinnerService().get_random_winner()
        if not winners:
            logger.info("Celery select_random_winner finished: no winners today")
            return
        logger.info(
            "Celery select_random_winner finished: winners=%s",
            [
                {
                    "user_id": w.user_id,
                    "promocode_id": w.promocode_id,
                    "prize": w.prize,
                    "place": w.place,
                }
                for w in winners
            ],
        )
    except WinnerAlreadySelectedToday:
        logger.info(
            "Celery select_random_winner skipped: winner already selected today"
        )


@shared_task(bind=True, name="generate_promocodes")
def generate_promocodes(self, count: int):
    logger.info("Celery generate_promocodes started: count=%s", count)
    started_at = timezone.now()
    started_at_iso = started_at.isoformat()
    task_id = self.request.id
    clear_promo_gen_cancel(task_id)

    def on_progress(created: int, total: int) -> None:
        self.update_state(
            state="PROGRESS",
            meta={
                "current": created,
                "total": total,
                "started_at": started_at_iso,
                "cancel_requested": is_promo_gen_cancelled(task_id),
            },
        )

    created, cancelled = PromoCodeService().generate_codes(
        count,
        progress_callback=on_progress,
        cancel_check=lambda: is_promo_gen_cancelled(task_id),
    )
    clear_promo_gen_cancel(task_id)
    elapsed_seconds = max(0, int((timezone.now() - started_at).total_seconds()))
    logger.info(
        "Celery generate_promocodes finished: requested=%s created=%s "
        "cancelled=%s elapsed_seconds=%s",
        count,
        created,
        cancelled,
        elapsed_seconds,
    )
    return {
        "created": created,
        "requested": count,
        "cancelled": cancelled,
        "started_at": started_at_iso,
        "elapsed_seconds": elapsed_seconds,
    }


def _parse_started_at(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _elapsed_seconds(
    started_at: datetime | None,
    *,
    finished_elapsed: int | None = None,
) -> int | None:
    if finished_elapsed is not None:
        return max(0, finished_elapsed)
    if started_at is None:
        return None
    return max(0, int((timezone.now() - started_at).total_seconds()))


def promo_gen_task_status(
    task_id: str,
    started_at: str | None = None,
) -> dict:
    """Снимок состояния задачи generate_promocodes для UI."""
    result = AsyncResult(task_id)
    state = result.state
    fallback_started = _parse_started_at(started_at)
    payload: dict = {
        "task_id": task_id,
        "state": state,
        "current": 0,
        "total": 0,
        "percent": 0,
        "done": False,
        "success": False,
        "cancelled": False,
        "cancel_requested": False,
        "error": None,
        "created": None,
        "requested": None,
        "started_at": started_at,
        "elapsed_seconds": _elapsed_seconds(fallback_started),
    }

    if state == "PENDING":
        payload["cancel_requested"] = is_promo_gen_cancelled(task_id)
        return payload

    if state == "PROGRESS":
        info = result.info or {}
        current = int(info.get("current") or 0)
        total = int(info.get("total") or 0)
        meta_started = _parse_started_at(info.get("started_at")) or fallback_started
        payload["current"] = current
        payload["total"] = total
        payload["percent"] = min(100, int(current * 100 / total)) if total > 0 else 0
        payload["started_at"] = meta_started.isoformat() if meta_started else started_at
        payload["elapsed_seconds"] = _elapsed_seconds(meta_started)
        payload["cancel_requested"] = bool(
            info.get("cancel_requested")
        ) or is_promo_gen_cancelled(task_id)
        return payload

    if state == "SUCCESS":
        info = result.result or {}
        if isinstance(info, dict):
            created = int(info.get("created") or 0)
            requested = int(info.get("requested") or 0)
            cancelled = bool(info.get("cancelled"))
            meta_started = _parse_started_at(info.get("started_at")) or fallback_started
            finished_elapsed = info.get("elapsed_seconds")
            finished_elapsed = (
                int(finished_elapsed) if finished_elapsed is not None else None
            )
        else:
            created = int(info or 0)
            requested = created
            cancelled = False
            meta_started = fallback_started
            finished_elapsed = None
        percent = (
            100
            if not cancelled and requested and created >= requested
            else (min(100, int(created * 100 / requested)) if requested else 0)
        )
        payload.update(
            {
                "done": True,
                "success": True,
                "cancelled": cancelled,
                "current": created,
                "total": requested or created,
                "percent": percent if cancelled else 100,
                "created": created,
                "requested": requested,
                "started_at": (
                    meta_started.isoformat() if meta_started else started_at
                ),
                "elapsed_seconds": _elapsed_seconds(
                    meta_started,
                    finished_elapsed=finished_elapsed,
                ),
            }
        )
        return payload

    if state == "FAILURE":
        payload["done"] = True
        payload["success"] = False
        payload["error"] = str(result.result)
        payload["percent"] = 0
        payload["elapsed_seconds"] = _elapsed_seconds(fallback_started)
        return payload

    # STARTED / RETRY / другие
    info = result.info if isinstance(result.info, dict) else {}
    if info:
        current = int(info.get("current") or 0)
        total = int(info.get("total") or 0)
        meta_started = _parse_started_at(info.get("started_at")) or fallback_started
        payload["current"] = current
        payload["total"] = total
        payload["percent"] = min(100, int(current * 100 / total)) if total > 0 else 0
        payload["started_at"] = meta_started.isoformat() if meta_started else started_at
        payload["elapsed_seconds"] = _elapsed_seconds(meta_started)
        payload["cancel_requested"] = bool(
            info.get("cancel_requested")
        ) or is_promo_gen_cancelled(task_id)
    return payload
