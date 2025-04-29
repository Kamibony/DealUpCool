# seed_db.py
import sqlite3
import logging
import json  # <- Přidán import JSON
from database import DATABASE_FILE  # Předpokládá, že database.py je ve stejném adresáři

# Nastavení logování
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

JSON_FILE = "calls.json"  # Název souboru s definicemi výzev


def seed_calls_from_json():
    conn = None
    try:
        # Načtení dat z JSON souboru
        try:
            with open(JSON_FILE, "r", encoding="utf-8") as f:
                calls_data = json.load(f)
            logging.info(
                f"Úspěšně načteno {len(calls_data)} výzev ze souboru {JSON_FILE}."
            )
        except FileNotFoundError:
            logging.error(f"Chyba: Soubor {JSON_FILE} nebyl nalezen.")
            return
        except json.JSONDecodeError as e:
            logging.error(f"Chyba při parsování souboru {JSON_FILE}: {e}")
            return
        except Exception as e:
            logging.error(f"Neočekávaná chyba při čtení souboru {JSON_FILE}: {e}")
            return

        # Připojení k DB
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        # 1. Smazání všech stávajících výzev (pro zajištění čistého stavu)
        try:
            deleted_count = cursor.execute("DELETE FROM calls").rowcount
            conn.commit()  # Potvrdíme smazání
            logging.info(
                f"Smazáno {deleted_count} existujících záznamů z tabulky 'calls'."
            )
        except sqlite3.Error as e:
            logging.error(f"Chyba při mazání starých výzev: {e}")
            # Můžeme se rozhodnout nepokračovat, pokud mazání selže
            # conn.close()
            # return

        # 2. Vložení nových výzev z JSON
        logging.info("Vkládání nových výzev z JSON...")
        inserted_count = 0
        for call in calls_data:
            try:
                # Ověření, zda máme všechny potřebné klíče (alespoň ty NOT NULL)
                if not all(k in call for k in ("name", "deal_price")):
                    logging.warning(
                        f"Přeskakuji záznam kvůli chybějícím klíčům (name/deal_price): {call.get('name', 'BEZ NÁZVU')}"
                    )
                    continue

                cursor.execute(
                    """
                    INSERT INTO calls (
                        name, description, original_price, deal_price, status,
                        data_needed, image_url, start_at, end_at, final_instructions
                    )
                    VALUES (:name, :description, :original_price, :deal_price, :status,
                            :data_needed, :image_url, :start_at, :end_at, :final_instructions)
                """,
                    {
                        # Použijeme .get() s defaultními hodnotami pro volitelné sloupce
                        "name": call["name"],
                        "description": call.get("description"),
                        "original_price": call.get("original_price"),
                        "deal_price": call["deal_price"],
                        "status": call.get("status", "active"),  # Defaultně active
                        "data_needed": call.get("data_needed"),
                        "image_url": call.get("image_url"),
                        "start_at": call.get("start_at"),
                        "end_at": call.get("end_at"),
                        "final_instructions": call.get("final_instructions"),
                    },
                )
                inserted_count += 1
                # logging.info(f" - Vloženo: {call['name']}") # Můžeme odkomentovat pro detailní log
            except sqlite3.Error as e:
                logging.error(
                    f" ! Chyba při vkládání '{call.get('name', 'BEZ NÁZVU')}': {e}"
                )

        conn.commit()  # Potvrdíme vložení všech záznamů
        logging.info(f"Úspěšně vloženo {inserted_count} výzev z {JSON_FILE}.")

    except sqlite3.Error as e:
        logging.error(f"Chyba při práci s databází: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        logging.error(f"Neočekávaná chyba ve skriptu seed_db.py: {e}")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    logging.info("Spouštím seedování databáze z JSON...")
    # Předpokládáme, že DB soubor a struktura tabulek existují
    # (vytvořeno spuštěním bot.py)
    seed_calls_from_json()
    logging.info("Seedování databáze dokončeno.")
