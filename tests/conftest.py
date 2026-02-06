import os

from app.start_code import get_start_code

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("DEV_TELEGRAM_USERNAME", "@dev-telegram-username")
os.environ.setdefault("TIMEOUT", "1")

get_start_code()
