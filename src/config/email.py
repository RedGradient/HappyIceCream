import sys

from django.core.mail.backends.base import BaseEmailBackend


class DecodedConsoleEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        for message in email_messages:
            sys.stdout.write(
                "\n---------- EMAIL ----------\n"
                f"To: {', '.join(message.to)}\n"
                f"From: {message.from_email}\n"
                f"Subject: {message.subject}\n"
                f"\n{message.body}\n"
                "---------------------------\n"
            )
            sys.stdout.flush()

        return len(email_messages)
