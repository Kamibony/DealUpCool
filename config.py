# config.py
import os
import logging  # Přidáno pro logování případných chyb v konfiguraci
from dotenv import load_dotenv

# Nastavení loggeru i pro konfigurační soubor
logger = logging.getLogger(__name__)

load_dotenv()  # Načte proměnné z .env souboru, pokud existuje

# --- Telegram Token ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    # Místo ValueError můžeme použít logger a ukončit/nebo nastavit default
    logger.critical(
        "KRITICKÁ CHYBA: Chybí TELEGRAM_BOT_TOKEN v .env souboru nebo proměnných prostředí!"
    )
    # V tomto případě je lepší ukončit, protože bez tokenu bot nemůže fungovat
    raise ValueError(
        "Chybí TELEGRAM_BOT_TOKEN v .env souboru nebo proměnných prostředí!"
    )

# --- Seznam Administrátorských ID ---
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")  # Načteme jako string, defaultně prázdný
ADMIN_IDS = set()  # Použijeme set pro rychlé ověření

if ADMIN_IDS_STR:
    try:
        # Rozdělíme string podle čárky a převedeme každé ID na číslo (integer)
        ADMIN_IDS = {
            int(admin_id.strip())
            for admin_id in ADMIN_IDS_STR.split(",")
            if admin_id.strip().isdigit()
        }
        logger.info(f"Načtena administrátorská ID: {ADMIN_IDS}")
    except ValueError:
        logger.error(
            f"Chyba při převodu ADMIN_IDS na čísla. Zkontrolujte formát v .env: '{ADMIN_IDS_STR}'"
        )
        # Můžeme zde vyvolat chybu nebo pokračovat bez adminů
else:
    logger.warning(
        "Proměnná ADMIN_IDS není nastavena v .env nebo proměnných prostředí. Žádný uživatel nebude mít admin práva."
    )
    # Pro testování můžete dočasně nastavit ID zde, ale nezapomeňte ho pak odstranit nebo dát do .env!
    # Například: ADMIN_IDS = {123456789} # VASE_TELEGRAM_ID

# --- Další možné konfigurace ---
# Např. limity, výchozí texty atd.
