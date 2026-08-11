from celery import shared_task

from promocode.exceptions import NoWinnerFound, WinnerAlreadySelectedToday
from promocode.services import WinnerService


@shared_task
def select_random_winner():
    try:
        WinnerService().get_random_winner()
    except WinnerAlreadySelectedToday:
        pass
    except NoWinnerFound:
        pass
