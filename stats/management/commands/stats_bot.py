import logging
import os

from django.core.management.base import BaseCommand, CommandError

from stats.bot import run_forever


class Command(BaseCommand):
    help = "Telegram statistics bot (long polling). Needs TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_IDS in .env."

    def handle(self, *args, **options):
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise CommandError("TELEGRAM_BOT_TOKEN is empty (.env)")
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        run_forever(token)
