# database.py
import sqlite3
import datetime
import logging
import json
import os  # Potřebujeme pro absolutní cestu

# --- Určení absolutní cesty k databázi ---
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_FILE = os.path.join(_BASE_DIR, "database.sqlite3")

# Nastavení loggeru
logger = logging.getLogger(__name__)
logger.info(f"Database path set to: {DATABASE_FILE}")  # Logování cesty pro kontrolu


def get_db_connection():
    """Vytvoří a vrátí spojení s databází."""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA encoding = 'UTF-8'")
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Chyba při připojování k databázi {DATABASE_FILE}: {e}")
        raise


# !! OPRAVENÁ VERZE init_db !!
def init_db():
    """Inicializuje databázi a vytvoří tabulky, pokud neexistují."""
    conn = None  # Inicializace pro finally blok
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Tabulka uživatelů
        # Použití trojitých uvozovek a standardní SQL syntaxe
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            consent_status TEXT DEFAULT 'pending',
            state TEXT DEFAULT 'start',
            joined_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
        )  # Ukončeno středníkem pro přehlednost
        logger.info("Tabulka 'users' zkontrolována/vytvořena.")

        # Tabulka Calls (Výzvy)
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS calls (
            call_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            original_price REAL,
            deal_price REAL NOT NULL,
            status TEXT DEFAULT 'active',
            data_needed TEXT,
            image_url TEXT,
            start_at DATETIME,
            end_at DATETIME,
            final_instructions TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
        )  # Ukončeno středníkem
        logger.info("Tabulka 'calls' zkontrolována/vytvořena.")

        # Tabulka Participations (Účasti)
        # Pečlivá kontrola syntaxe FOREIGN KEY a UNIQUE
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS participations (
            participation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            call_id INTEGER NOT NULL,
            status TEXT DEFAULT 'interested',
            collected_data TEXT,
            participation_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (telegram_id) ON DELETE CASCADE,
            FOREIGN KEY (call_id) REFERENCES calls (call_id) ON DELETE CASCADE,
            UNIQUE(user_id, call_id)
        );
        """
        )  # Ukončeno středníkem
        logger.info("Tabulka 'participations' zkontrolována/vytvořena.")

        conn.commit()  # Potvrdíme všechny změny
        logger.info("Inicializace databáze dokončena.")

    except sqlite3.Error as e:
        logger.error(f"Chyba během inicializace DB: {e}")
        # Pokud nastane chyba, nemá smysl pokračovat
        if conn:
            conn.rollback()  # Vrátíme případné částečné změny
        raise  # Znovu vyvoláme výjimku, aby ji zachytil main a ukončil bota
    finally:
        if conn:
            conn.close()  # Vždy uzavřeme spojení


# --- Ostatní Funkce pro práci s DB (zůstávají stejné) ---


def get_active_calls():
    """Načte všechny aktivní výzvy z databáze."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT call_id, name, description, original_price, deal_price FROM calls WHERE status = 'active' ORDER BY created_at DESC"
        )
        calls = cursor.fetchall()
        logger.info(
            f"DEBUG get_active_calls: Načteno řádků: {len(calls)}. První řádek (pokud existuje): {dict(calls[0]) if calls else 'Žádný'}"
        )
        conn.close()
        return calls
    except sqlite3.Error as e:
        logger.error(f"Chyba při načítání aktivních výzev: {e}")
        return []


def get_call_details(call_id: int):
    """Načte všechny detaily konkrétní výzvy podle ID."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM calls WHERE call_id = ?", (call_id,))
        call = cursor.fetchone()
        conn.close()
        return call
    except sqlite3.Error as e:
        logger.error(f"Chyba při načítání detailu výzvy ID {call_id}: {e}")
        return None


def update_user_consent(user_id: int, consent_status: str):
    """Aktualizuje stav souhlasu uživatele."""
    allowed_statuses = ["pending", "granted", "denied"]
    if consent_status not in allowed_statuses:
        logger.error(
            f"Neplatný consent_status '{consent_status}' pro uživatele {user_id}"
        )
        return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET consent_status = ? WHERE telegram_id = ?",
            (consent_status, user_id),
        )
        conn.commit()
        conn.close()
        logger.info(
            f"Consent status pro uživatele {user_id} aktualizován na {consent_status}."
        )
        return True
    except sqlite3.Error as e:
        logger.error(f"Chyba při ukládání souhlasu uživatele {user_id}: {e}")
        return False


def add_or_update_user(user_id: int, first_name: str, last_name: str, username: str):
    """Přidá nebo aktualizuje uživatele."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (telegram_id, first_name, last_name, username) VALUES (?, ?, ?, ?) ON CONFLICT(telegram_id) DO UPDATE SET first_name=excluded.first_name, last_name=excluded.last_name, username=excluded.username, joined_timestamp=CURRENT_TIMESTAMP",
            (user_id, first_name or "", last_name or "", username or ""),
        )
        conn.commit()
        conn.close()
        logger.info(f"Uživatel {user_id} uložen/aktualizován v DB.")
        return True
    except sqlite3.Error as e:
        logger.error(f"Chyba při ukládání uživatele {user_id} do DB: {e}")
        return False


def add_or_update_participation(
    user_id: int, call_id: int, status: str, collected_data: dict = None
):
    """Přidá nebo aktualizuje účast uživatele ve výzvě (ukládá data jako JSON)."""
    allowed_statuses = ["interested", "data_collected", "confirmed", "cancelled"]
    data_json = None
    if status not in allowed_statuses:
        logger.error(
            f"Neplatný participation status '{status}' pro user {user_id}, call {call_id}"
        )
        return False
    if collected_data is not None and status != "cancelled":
        try:
            data_json = json.dumps(collected_data, ensure_ascii=False)
        except TypeError as e:
            logger.error(
                f"Chyba při převodu collected_data na JSON pro user {user_id}, call {call_id}: {e}"
            )
            return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO participations (user_id, call_id, status, collected_data) VALUES (?, ?, ?, ?) ON CONFLICT(user_id, call_id) DO UPDATE SET status=excluded.status, collected_data=CASE WHEN excluded.status = 'cancelled' THEN NULL ELSE excluded.collected_data END, participation_timestamp=CURRENT_TIMESTAMP",
            (user_id, call_id, status, data_json),
        )
        conn.commit()
        conn.close()
        logger.info(
            f"Účast pro user {user_id}, call {call_id} přidána/aktualizována na status {status}."
        )
        return True
    except sqlite3.Error as e:
        logger.error(f"Chyba při ukládání účasti user {user_id}, call {call_id}: {e}")
        return False


def get_participation(user_id: int, call_id: int):
    """Načte detaily účasti a převede collected_data z JSON na slovník."""
    participation = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM participations WHERE user_id = ? AND call_id = ?",
            (user_id, call_id),
        )
        participation_row = cursor.fetchone()
        conn.close()
        if participation_row:
            participation = dict(participation_row)
            if participation.get("collected_data"):
                try:
                    participation["collected_data"] = json.loads(
                        participation["collected_data"]
                    )
                except json.JSONDecodeError:
                    logger.error(
                        f"Chyba dekódování JSON pro user {user_id}, call {call_id}"
                    )
                    participation["collected_data"] = {}
            else:
                participation["collected_data"] = {}
        return participation
    except sqlite3.Error as e:
        logger.error(f"Chyba při načítání účasti user {user_id}, call {call_id}: {e}")
        return None


def get_user_active_participations(user_id: int):
    """Načte aktivní účasti uživatele a připojí název výzvy."""
    participations = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT p.participation_id, p.call_id, p.status, c.name as call_name FROM participations p JOIN calls c ON p.call_id = c.call_id WHERE p.user_id = ? AND p.status IN ('interested', 'data_collected', 'confirmed') ORDER BY p.participation_timestamp DESC",
            (user_id,),
        )
        participations = cursor.fetchall()
        conn.close()
        return participations
    except sqlite3.Error as e:
        logger.error(
            f"Chyba při načítání aktivních účastí pro uživatele {user_id}: {e}"
        )
        return []


def add_new_call(
    name: str,
    description: str | None,
    original_price: float | None,
    deal_price: float,
    status: str,
    data_needed: str | None,
    final_instructions: str | None,
    image_url: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
) -> int | None:
    """Vloží novou výzvu do databáze a vrátí její ID, nebo None při chybě."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO calls (name, description, original_price, deal_price, status, data_needed, image_url, start_at, end_at, final_instructions) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                description,
                original_price,
                deal_price,
                status,
                data_needed,
                image_url,
                start_at,
                end_at,
                final_instructions,
            ),
        )
        conn.commit()
        new_call_id = cursor.lastrowid
        logger.info(f"Nová výzva '{name}' úspěšně vložena s ID: {new_call_id}")
        conn.close()
        return new_call_id
    except sqlite3.Error as e:
        logger.error(f"Chyba při vkládání nové výzvy '{name}': {e}")
        if conn:
            conn.rollback()
            conn.close()
        return None
