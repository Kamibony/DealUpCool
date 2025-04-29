import os
from dotenv import load_dotenv

load_dotenv()  # Načte proměnné z .env souboru

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError(
        "Chybí TELEGRAM_BOT_TOKEN v .env souboru nebo proměnných prostředí!"
    )

# Zde můžeme přidat další konfigurace později
