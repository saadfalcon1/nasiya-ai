import asyncio
import logging

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Nasiya AI Telegram botini ishga tushiradi"

    def handle(self, *args, **options):
        logging.basicConfig(level=logging.INFO)
        from shop.bot import run
        asyncio.run(run())
