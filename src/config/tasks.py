import logging

from celery import shared_task

from promocode.exceptions import WinnerAlreadySelectedToday
from promocode.services import PromoCodeService, WinnerService

logger = logging.getLogger(__name__)

DEFAULT_PROMO_SEED_COUNT = 1_500_000


@shared_task(name="select_random_winner")
def select_random_winner():
    try:
        winners = WinnerService().get_random_winner()
        if not winners:
            logger.info("Celery select_random_winner finished: no winners today")
            return
        logger.info(
            "Celery select_random_winner finished: winners=%s",
            [{"user_id": w.user_id, "promocode_id": w.promocode_id} for w in winners],
        )
    except WinnerAlreadySelectedToday:
        logger.info(
            "Celery select_random_winner skipped: winner already selected today"
        )


@shared_task(name="generate_promocodes")
def generate_promocodes(count: int = DEFAULT_PROMO_SEED_COUNT):
    logger.info("Celery generate_promocodes started: count=%s", count)
    created = PromoCodeService().generate_codes(count)
    logger.info(
        "Celery generate_promocodes finished: requested=%s created=%s",
        count,
        created,
    )
    return created
