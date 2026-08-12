class PromocodeDoesNotExist(Exception):
    pass


class PromocodeAlreadyUsed(Exception):
    pass


class NoWinnerFound(Exception):
    pass


class WinnerAlreadySelectedToday(Exception):
    pass
