import logging

from celery import shared_task

from promocode.exceptions import NoWinnerFound, WinnerAlreadySelectedToday
from promocode.services import WinnerService

logger = logging.getLogger(__name__)


@shared_task(name="select_random_winner")
def select_random_winner():
    try:
        winner = WinnerService().get_random_winner()
        logger.info(
            "Celery select_random_winner finished: user_id=%s promocode_id=%s",
            winner.user_id,
            winner.promocode_id,
        )
    except WinnerAlreadySelectedToday:
        logger.info(
            "Celery select_random_winner skipped: winner already selected today"
        )
    except NoWinnerFound:
        logger.warning("Celery select_random_winner failed: no winner candidates")
