import logging
from datetime import datetime

from celery import shared_task
from celery.result import AsyncResult
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from promocode.exceptions import WinnerAlreadySelectedToday
from promocode.services import PromoCodeService, WinnerService

logger = logging.getLogger(__name__)

SESSION_PROMO_GEN_TASK_ID = "promo_gen_task_id"
SESSION_PROMO_GEN_STARTED_AT = "promo_gen_started_at"


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

    def on_progress(created: int, total: int) -> None:
        self.update_state(
            state="PROGRESS",
            meta={
                "current": created,
                "total": total,
                "started_at": started_at_iso,
            },
        )

    created = PromoCodeService().generate_codes(
        count,
        progress_callback=on_progress,
    )
    elapsed_seconds = max(0, int((timezone.now() - started_at).total_seconds()))
    logger.info(
        "Celery generate_promocodes finished: requested=%s created=%s "
        "elapsed_seconds=%s",
        count,
        created,
        elapsed_seconds,
    )
    return {
        "created": created,
        "requested": count,
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
        "error": None,
        "created": None,
        "requested": None,
        "started_at": started_at,
        "elapsed_seconds": _elapsed_seconds(fallback_started),
    }

    if state == "PENDING":
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
        return payload

    if state == "SUCCESS":
        info = result.result or {}
        if isinstance(info, dict):
            created = int(info.get("created") or 0)
            requested = int(info.get("requested") or 0)
            meta_started = _parse_started_at(info.get("started_at")) or fallback_started
            finished_elapsed = info.get("elapsed_seconds")
            finished_elapsed = (
                int(finished_elapsed) if finished_elapsed is not None else None
            )
        else:
            created = int(info or 0)
            requested = created
            meta_started = fallback_started
            finished_elapsed = None
        payload.update(
            {
                "done": True,
                "success": True,
                "current": created,
                "total": requested or created,
                "percent": 100,
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
    return payload
