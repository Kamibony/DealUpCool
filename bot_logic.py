# bot_logic.py
import logging
from telegram.constants import ParseMode  # Importujeme pro případné použití zde

# Importujeme databázové funkce, které budeme volat
from database import get_call_details, get_participation, add_or_update_participation

logger = logging.getLogger(__name__)


def format_calls_list_message(active_calls):
    """
    Sestaví text zprávy se seznamem aktivních výzev pro odeslání uživateli.
    Vrací string.
    """
    if not active_calls:
        return "Momentálně nejsou k dispozici žádné aktivní Výzvy."

    message_parts = ["Zde jsou aktuální aktivní Výzvy:\n"]
    for call in active_calls:
        try:
            call_id = call["call_id"]
            name = call["name"]
            description = call["description"] or ""
            original_price = call["original_price"]
            deal_price = call["deal_price"]

            original_price_str = (
                f"~{str(original_price).replace('.', r'\.')} Kč~"
                if original_price is not None
                else ""
            )
            deal_price_str = str(deal_price).replace(".", r"\.")

            message_parts.append(
                f"\n*{name}*\n"
                f"{description}\n"
                f"Cena: {original_price_str} -> *{deal_price_str} Kč*\n"
                f"--------------------"
            )
        except KeyError as e:
            logger.error(
                f"Chybějící klíč '{e}' ve 'call' datech při formátování výzvy ID {call.get('call_id', '?') if isinstance(call, dict) else 'N/A'}"
            )
            message_parts.append(
                f"\n*Chyba při načítání detailů výzvy*\n--------------------"
            )
        except Exception as e:
            logger.error(
                f"Neočekávaná chyba při formátování výzvy {call.get('call_id', '?') if isinstance(call, dict) else 'N/A'}: {e}"
            )
            message_parts.append(
                f"\n*Chyba při načítání detailů výzvy*\n--------------------"
            )

    return "\n".join(message_parts)


def process_call_selection(user_id: int, call_id: int, user_first_name: str):
    """
    Zpracuje logiku po výběru výzvy uživatelem.
    Načte data, provede kontroly, aktualizuje DB a vrátí výsledek pro handler.

    Vrací slovník s klíči:
        'status': 'ok' / 'info' / 'error'
        'message': Text zprávy pro uživatele (pro editaci nebo odeslání)
        'next_state': Další stav pro ConversationHandler (None pokud končí)
        'user_data_updates': Slovník s daty pro aktualizaci context.user_data (volitelné)
    """
    logger.info(f"BOT_LOGIC: Zpracovávám výběr výzvy {call_id} pro uživatele {user_id}")

    call_details = get_call_details(call_id)

    # Kontrola existence a stavu výzvy
    if not call_details or call_details["status"] != "active":
        call_name = call_details["name"] if call_details else f"ID {call_id}"
        return {
            "status": "error",
            "message": f"Výzva '{call_name}' již není aktivní nebo neexistuje.",
            "next_state": -1,  # Použijeme -1 pro ConversationHandler.END
        }

    # Kontrola existující účasti
    participation = get_participation(user_id, call_id)
    if participation and participation["status"] not in ["interested", "cancelled"]:
        return {
            "status": "info",
            "message": f"V této Výzvě ('{call_details['name']}') již máš zaznamenanou účast (stav: {participation['status']}). Pro zrušení použij /zrusit_ucast.",
            "next_state": -1,
        }

    # Přidání/aktualizace účasti na 'interested'
    if not add_or_update_participation(user_id, call_id, status="interested"):
        return {
            "status": "error",
            "message": "Nastala chyba při záznamu tvého zájmu. Zkus to prosím znovu.",
            "next_state": -1,
        }

    # Kontrola, zda jsou potřeba data
    data_needed_str = None
    try:
        data_needed_str = call_details["data_needed"]
    except IndexError:
        logger.warning(f"Sloupec 'data_needed' chybí pro call_id {call_id}.")

    if data_needed_str:
        data_needed_list = [
            item.strip() for item in data_needed_str.split(",") if item.strip()
        ]
        if not data_needed_list:
            # Prázdný data_needed -> potvrdit rovnou
            logger.info(
                f"Výzva {call_id} má prázdný data_needed, beru jako nepotřebu dat."
            )
            # Bezpečný přístup k final_instructions a name
            final_instructions = "Účast potvrzena! Další instrukce brzy."
            call_name = f"Výzva ID {call_id}"
            if call_details:
                try:
                    call_name = call_details["name"] or call_name
                except IndexError:
                    pass
                try:
                    final_instructions = (
                        call_details["final_instructions"] or final_instructions
                    )
                except IndexError:
                    logger.warning(
                        f"Sloupec 'final_instructions' chybí pro call_id {call_id}."
                    )

            if add_or_update_participation(
                user_id, call_id, status="confirmed", collected_data={}
            ):
                return {
                    "status": "ok",
                    "message": f"Skvělé, {user_first_name}! Účast ve Výzvě *{call_name}* potvrzena!\n\n{final_instructions}",
                    "next_state": -1,  # ConversationHandler.END
                }
            else:
                return {
                    "status": "error",
                    "message": "Chyba při potvrzování účasti.",
                    "next_state": -1,
                }
        else:
            # Data jsou potřeba -> připravit data pro ConversationHandler
            call_name = call_details["name"] if call_details else f"ID {call_id}"
            user_data_updates = {
                "current_call_id": call_id,
                "data_needed_list": data_needed_list,
                "data_needed_index": 0,
                "collected_data_so_far": {},
                "current_data_key": None,
            }
            logger.info(
                f"BOT_LOGIC: User {user_id} startuje sběr dat pro call {call_id}, potřeba: {data_needed_list}"
            )
            return {
                "status": "ok",
                "message": f"Super! Zájem o *{call_name}* zaznamenán.\nNyní potřebuji pár údajů. Pro zrušení napiš /cancel.",
                "next_state": 0,  # ASKING_DATA (nebo který stav použijeme jako první)
                "user_data_updates": user_data_updates,
            }

    else:  # data_needed je NULL -> potvrdit rovnou
        final_instructions = "Účast potvrzena! Další instrukce brzy."
        call_name = f"Výzva ID {call_id}"
        if call_details:
            try:
                call_name = call_details["name"] or call_name
            except IndexError:
                pass
            try:
                final_instructions = (
                    call_details["final_instructions"] or final_instructions
                )
            except IndexError:
                logger.warning(
                    f"Sloupec 'final_instructions' chybí pro call_id {call_id}."
                )

        if add_or_update_participation(
            user_id, call_id, status="confirmed", collected_data={}
        ):
            return {
                "status": "ok",
                "message": f"Skvělé, {user_first_name}! Účast ve Výzvě *{call_name}* potvrzena!\n\n{final_instructions}",
                "next_state": -1,  # ConversationHandler.END
            }
        else:
            return {
                "status": "error",
                "message": "Chyba při potvrzování účasti.",
                "next_state": -1,
            }


# --- Zde budeme přidávat další logické funkce ---
# Např. pro validaci, formátování finálních kroků atd.
