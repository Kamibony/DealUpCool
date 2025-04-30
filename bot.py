# bot.py
import logging
import json
import re
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)
from telegram.constants import ParseMode

# --- Importy ---
from config import TELEGRAM_TOKEN

# Importujeme databázové funkce
from database import (
    init_db,
    get_db_connection,
    get_active_calls,
    get_call_details,
    update_user_consent,
    add_or_update_user,
    add_or_update_participation,
    get_participation,
    get_user_active_participations,
)

# Importujeme logiku z nového souboru
import bot_logic  # <-- DŮLEŽITÝ IMPORT

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Stavy konverzace ---
ASKING_DATA, PROCESSING_DATA = range(2)  # 0, 1

# --- Běžné Handlery ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Odešle uvítací zprávu a žádost o souhlas."""
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "Uživateli"  # Fallback, pokud jméno není dostupné
    username = user.username
    last_name = user.last_name

    logger.info(f"User {user_id} ({username or 'bez @'}) spustil /start.")

    if not add_or_update_user(user_id, first_name, last_name, username):
        await update.message.reply_text("Omlouvám se, nastala interní chyba.")
        return ConversationHandler.END  # Ukončíme konverzaci, pokud by byla aktivní

    welcome_message = (
        f"Ahoj {first_name}! Vítej v DealUpBotu.\n\n"
        "Pomáhám lidem spojit se pro kolektivní nákupy ('Výzvy') a získat tak lepší ceny.\n\n"
        "Než začneme, potřebuji tvůj **souhlas se zpracováním údajů** (Telegram ID, jméno) "
        "a **zasíláním nabídek** ('Výzev'). Souhlasíš?"
    )
    reply_keyboard = [
        [KeyboardButton("Ano, souhlasím 👍")],
        [KeyboardButton("Ne, děkuji")],
    ]
    markup = ReplyKeyboardMarkup(
        reply_keyboard, resize_keyboard=True, one_time_keyboard=True
    )
    await update.message.reply_text(
        welcome_message, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
    )
    # Vrátíme END pro případ, že by se /start zavolal během jiné konverzace
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Odešle nápovědu jako prostý text."""
    help_text = (
        "Jsem DealUpBot a pomohu ti s kolektivními nákupy ('Výzvami').\n\n"
        "Základní příkazy:\n"
        "/start - Úvod a udělení souhlasu.\n"
        "/vyzvy - Zobrazí aktuální aktivní Výzvy.\n"
        "/zrusit_ucast - Umožní zrušit tvou účast v aktivní Výzvě.\n"
        "/help - Zobrazí tuto nápovědu.\n"
        "/cancel - Zruší aktuálně probíhající akci (např. sběr údajů).\n"
    )
    # OPRAVA: Odebrán parametr parse_mode=ParseMode.MARKDOWN
    await update.message.reply_text(help_text)


async def handle_consent_response(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Zpracuje odpověď na souhlas."""
    user_id = update.effective_user.id
    response = update.message.text
    logger.info(f"User {user_id} odpověděl na souhlas: {response}")
    new_consent_status = "pending"
    reply_text = ""
    show_calls_after = False

    if "Ano, souhlasím" in response:
        new_consent_status = "granted"
        reply_text = "Děkuji za souhlas! 🎉 Nyní ti mohu zasílat zajímavé 'Výzvy'."
        show_calls_after = True
    elif "Ne, děkuji" in response:
        new_consent_status = "denied"
        reply_text = "Rozumím. Nebudu ti tedy zasílat žádné nabídky..."

    if update_user_consent(user_id, new_consent_status):
        await update.message.reply_text(reply_text, reply_markup=ReplyKeyboardRemove())
        if show_calls_after:
            await list_calls(update, context)  # Zavoláme zobrazení výzev
    else:
        await update.message.reply_text(
            "Chyba při ukládání volby.", reply_markup=ReplyKeyboardRemove()
        )


async def list_calls(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Zobrazí seznam aktivních Výzev s inline tlačítky."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} spouští zobrazení výzev.")

    # TODO: Zkontrolovat consent_status=='granted' zde!

    active_calls = get_active_calls()

    # !! REFAKTORING: Použijeme funkci z bot_logic pro sestavení textu !!
    message_text = bot_logic.format_calls_list_message(active_calls)

    keyboard = []
    reply_markup = None
    if active_calls:  # Tlačítka přidáme jen pokud jsou výzvy
        for call in active_calls:
            try:
                # Přístup k 'call_id' a 'name' by měl být bezpečný
                button = InlineKeyboardButton(
                    f"Mám zájem: {call['name']} ({call['deal_price']} Kč)",
                    callback_data=f"call_{call['call_id']}",
                )
                keyboard.append([button])
            except KeyError as e:
                logger.error(
                    f"Chybějící klíč '{e}' ve 'call' datech při tvorbě tlačítka pro list_calls."
                )
            except Exception as e:
                logger.error(
                    f"Neočekávaná chyba při tvorbě tlačítka pro list_calls: {e}"
                )

        if keyboard:
            reply_markup = InlineKeyboardMarkup(keyboard)

    # Odešleme zprávu
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=message_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as md_error:
        logger.warning(
            f"Nepodařilo se poslat list_calls s Markdown: {md_error}. Posílám jako prostý text."
        )
        plain_text = (
            message_text.replace("*", "").replace("~", "").replace(r"\.", ".")
        )  # Základní odstranění Markdown
        await context.bot.send_message(
            chat_id=chat_id, text=plain_text, reply_markup=reply_markup
        )


# --- ConversationHandler pro sběr dat (začátek) ---


# !! REFAKTORING: Tato funkce nyní volá bot_logic.process_call_selection !!
async def handle_call_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int | None:
    """
    Zpracuje výběr Výzvy (CallbackQuery) zavoláním logiky z bot_logic.
    Nastaví user_data a vrátí další stav pro ConversationHandler podle výsledku.
    """
    query = update.callback_query
    await query.answer()  # Potvrdíme Telegramu příjem rychle
    callback_data = query.data
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "Uživateli"
    logger.info(f"HANDLER: User {user_id} stiskl tlačítko: {callback_data}")

    if not callback_data.startswith("call_"):
        logger.warning(
            f"HANDLER: User {user_id} poslal neočekávaný callback (ne call_): {callback_data}"
        )
        return None  # Tento callback není pro nás

    next_state = ConversationHandler.END  # Defaultní stav je ukončení

    try:
        call_id = int(callback_data.split("_")[1])

        # Zavoláme funkci z bot_logic, která obsahuje všechnu logiku
        # Předáme jí potřebné údaje pro zpracování a formátování
        result = bot_logic.process_call_selection(user_id, call_id, first_name)

        # Zpracujeme výsledek z bot_logic
        if result["status"] == "error" or result["status"] == "info":
            # Pro informační/chybové zprávy nepoužíváme Markdown
            await query.edit_message_text(text=result["message"], reply_markup=None)
            # next_state zůstává END

        elif result["status"] == "ok":
            # Zpráva je již připravena v result['message'] (buď potvrzení zájmu, nebo finální potvrzení)
            # U finálního potvrzení pro výzvy bez dat je nyní (pro test) zjednodušená
            final_message = result["message"]
            state_code = result.get("next_state")

            # Upravíme původní zprávu
            # Pro finální potvrzení (state_code == -1) nyní nepoužíváme Markdown
            # Pro potvrzení zájmu (state_code == ASKING_DATA) můžeme Markdown ponechat
            use_markdown = state_code != -1
            await query.edit_message_text(
                text=final_message,
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN if use_markdown else None,
            )

            # Aktualizace user_data, pokud je potřeba (pro start sběru dat)
            if "user_data_updates" in result:
                context.user_data.update(result["user_data_updates"])

            # Vrácení dalšího stavu
            if state_code == ASKING_DATA:  # 0
                # Zavoláme funkci pro položení první otázky
                return await ask_next_data(update, context)
            else:  # state_code je -1 nebo None
                next_state = ConversationHandler.END
                # Vyčistíme user_data pro jistotu
                for key in list(context.user_data.keys()):
                    if key.startswith("current_") or key in [
                        "data_needed_list",
                        "data_needed_index",
                        "collected_data_so_far",
                    ]:
                        context.user_data.pop(key, None)
        else:
            # Neznámý status z bot_logic
            logger.error(
                f"Neznámý status '{result.get('status')}' vrácen z process_call_selection."
            )
            await query.edit_message_text("Nastala neočekávaná chyba.")
            next_state = ConversationHandler.END

        return next_state

    except (IndexError, ValueError) as e:
        logger.error(
            f"HANDLER: Neplatný formát call_ callback_data: {callback_data} pro user {user_id}. Chyba: {e}"
        )
        await context.bot.send_message(
            chat_id=query.message.chat_id, text="Chyba při zpracování volby."
        )
        return ConversationHandler.END
    except Exception as e:
        # Zachytíme i případnou telegram.error.BadRequest z edit_message_text
        logger.error(
            f"HANDLER: Neočekávaná chyba při handle_call_selection {callback_data} pro user {user_id}: {e}"
        )
        # Pokusíme se poslat novou zprávu místo editace, pokud nastala chyba
        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Neočekávaná chyba při zpracování vaší volby.",
            )
        except Exception as send_e:
            logger.error(
                f"HANDLER: Nepodařilo se odeslat ani chybovou zprávu uživateli {user_id}: {send_e}"
            )
        return ConversationHandler.END


async def ask_next_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Zeptá se na další údaj nebo ukončí konverzaci a zobrazí naformátované finální instrukce."""
    user_data = context.user_data
    needed_list = user_data.get("data_needed_list", [])
    current_index = user_data.get("data_needed_index", 0)
    chat_id = (
        update.effective_chat.id
        if update.effective_chat
        else (update.callback_query.message.chat_id if update.callback_query else None)
    )
    if not chat_id:
        logger.error("Nemohu získat chat_id v ask_next_data")
        return ConversationHandler.END

    if current_index >= len(needed_list):
        # --- Všechna data shromážděna ---
        user = update.effective_user
        user_id = user.id
        first_name = user.first_name or "Uživateli"
        call_id = user_data.get("current_call_id")
        logger.info(f"User {user_id}: Všechna data pro call {call_id} shromážděna.")
        collected_data = user_data.get("collected_data_so_far", {})

        call_details = get_call_details(call_id)
        instruction_template = "Další instrukce brzy."
        call_name = f"Výzva ID {call_id}"
        deal_price = "N/A"
        if call_details:
            try:
                call_name = call_details["name"] or call_name
            except IndexError:
                pass
            try:
                deal_price = call_details["deal_price"]
            except IndexError:
                pass
            try:
                instruction_template = (
                    call_details["final_instructions"] or instruction_template
                )
            except IndexError:
                logger.warning(
                    f"Sloupec 'final_instructions' chybí pro call_id {call_id} v ask_next_data."
                )

        if add_or_update_participation(
            user_id=user_id,
            call_id=call_id,
            status="data_collected",
            collected_data=collected_data,
        ):
            format_data = {
                "user_first_name": first_name,
                "user_id": user_id,
                "call_name": call_name,
                "deal_price": deal_price,
                "call_id": call_id,
            }
            format_data.update(collected_data)  # Přidáme i nasbíraná data
            try:
                formatted_instructions = instruction_template.format(**format_data)
            except KeyError as e:
                logger.error(
                    f"Chybějící klíč '{e}' při formátování final_instructions (po sběru dat)."
                )
                formatted_instructions = instruction_template
            except Exception as e:
                logger.error(f"Jiná chyba formátování final_instructions: {e}")
                formatted_instructions = instruction_template

            confirmation_message = (
                "Děkuji! Všechny potřebné údaje byly zaznamenány.\n\n**Shrnutí:**\n"
            )
            for key, value in collected_data.items():
                confirmation_message += (
                    f"- {key.replace('_', ' ').capitalize()}: {value}\n"
                )
            confirmation_message += f"\n**Další kroky:**\n{formatted_instructions}"
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=confirmation_message,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as md_error:
                logger.warning(
                    f"Nepodařilo se poslat final confirmation s Markdown: {md_error}. Posílám jako prostý text."
                )
                plain_text = confirmation_message.replace("**", "")
                await context.bot.send_message(chat_id=chat_id, text=plain_text)
        else:
            await context.bot.send_message(
                chat_id=chat_id, text="Chyba při ukládání údajů."
            )

        for key in list(user_data.keys()):
            if key.startswith("current_") or key in [
                "data_needed_list",
                "data_needed_index",
                "collected_data_so_far",
            ]:
                user_data.pop(key, None)
        return ConversationHandler.END
    else:
        # --- Zeptáme se na další údaj ---
        data_key = needed_list[current_index].strip()
        user_data["current_data_key"] = data_key
        questions = {
            "adresa doručení": "Prosím, zadej **adresu doručení** (ulice, č.p., město, PSČ):",
            "telefonní číslo": "Prosím, zadej své **telefonní číslo**:",
            "počet kusů": "Prosím, zadej požadovaný **počet kusů**:",
            "email": "Prosím, zadej svou **emailovou adresu**:",
        }
        question_text = questions.get(
            data_key.lower(), f"Prosím, zadej údaj pro: **{data_key}**"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=question_text, parse_mode=ParseMode.MARKDOWN
        )
        return PROCESSING_DATA


async def process_data_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Zpracuje a validuje odpověď uživatele."""
    # (kód process_data_input zůstává stejný s validací)
    user_data = context.user_data
    user_input = update.message.text
    user_id = update.effective_user.id
    current_key = user_data.get("current_data_key")
    if not current_key:
        logger.warning(f"User {user_id} poslal '{user_input}', ale nečekal se údaj.")
        return PROCESSING_DATA
    logger.info(f"User {user_id} zadal údaj '{user_input}' pro '{current_key}'")
    is_valid = True
    error_message = ""
    processed_input = user_input.strip()
    key_lower = current_key.lower()
    if key_lower == "počet kusů":
        if not processed_input.isdigit() or int(processed_input) <= 0:
            is_valid = False
            error_message = "Toto není kladné číslo. Zadej počet kusů (např. 1):"
        else:
            processed_input = int(processed_input)
    elif key_lower == "email":
        if not re.match(
            r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", processed_input
        ):
            is_valid = False
            error_message = (
                "Toto není platný email. Zadej ho znovu (např. jmeno@domena.cz):"
            )
    elif key_lower == "telefonní číslo":
        cleaned_phone = re.sub(r"[\s()-]+", "", processed_input)
        if not re.match(r"^\+?\d{9,15}$", cleaned_phone):
            is_valid = False
            error_message = (
                "Toto není platný telefon. Zadej ho znovu (např. +420123456789):"
            )
        else:
            processed_input = cleaned_phone
    elif key_lower == "adresa doručení":
        if len(processed_input) < 10:
            is_valid = False
            error_message = "Adresa je příliš krátká. Zadej ji prosím znovu:"
    if not is_valid:
        await update.message.reply_text(error_message)
        return PROCESSING_DATA
    user_data.setdefault("collected_data_so_far", {})[current_key] = processed_input
    user_data["data_needed_index"] = user_data.get("data_needed_index", 0) + 1
    user_data.pop("current_data_key", None)
    return await ask_next_data(update, context)


async def cancel_conversation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Ukončí ConversationHandler."""
    # (kód cancel_conversation zůstává stejný)
    user = update.effective_user
    user_data = context.user_data
    call_id = user_data.get("current_call_id")
    logger.info(
        f"User {user.id} zrušil konverzaci (během sběru dat pro call {call_id})."
    )
    if call_id:
        if not add_or_update_participation(
            user_id=user.id, call_id=call_id, status="cancelled"
        ):
            logger.error(
                f"Nepodařilo se aktualizovat status na 'cancelled' pro user {user.id}, call {call_id}"
            )
    await update.message.reply_text(
        "Akce byla zrušena.", reply_markup=ReplyKeyboardRemove()
    )
    for key in list(user_data.keys()):
        if key.startswith("current_") or key in [
            "data_needed_list",
            "data_needed_index",
            "collected_data_so_far",
        ]:
            user_data.pop(key, None)
    return ConversationHandler.END


# --- Handlery pro /zrusit_ucast ---
# (cancel_participation_start a handle_cancel_selection zůstávají stejné)
async def cancel_participation_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} spustil /zrusit_ucast")
    active_participations = get_user_active_participations(user_id)
    if not active_participations:
        await update.message.reply_text("Nemáš žádné aktivní účasti.")
        return
    message_text = "Tvé aktivní účasti. Vyber, kterou chceš zrušit:\n"
    keyboard = []
    for part in active_participations:
        button_text = f"Zrušit: {part['call_name']} (Stav: {part['status']})"
        callback_data = f"cancel_{part['call_id']}"
        keyboard.append(
            [InlineKeyboardButton(button_text, callback_data=callback_data)]
        )
    keyboard.append([InlineKeyboardButton("Zpět", callback_data="cancel_abort")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message_text, reply_markup=reply_markup)


async def handle_cancel_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    callback_data = query.data
    user_id = query.from_user.id
    logger.info(f"User {user_id} stiskl tlačítko zrušení: {callback_data}")
    if callback_data == "cancel_abort":
        await query.edit_message_text("Akce zrušena.", reply_markup=None)
        return
    if callback_data.startswith("cancel_"):
        try:
            call_id_to_cancel = int(callback_data.split("_")[1])
            if add_or_update_participation(
                user_id, call_id_to_cancel, status="cancelled", collected_data=None
            ):
                call_details = get_call_details(call_id_to_cancel)
                call_name = (
                    call_details["name"] if call_details else f"ID {call_id_to_cancel}"
                )
                await query.edit_message_text(
                    f"Účast ve Výzvě '{call_name}' zrušena.", reply_markup=None
                )
                logger.info(
                    f"User {user_id} zrušil účast ve výzvě {call_id_to_cancel}."
                )
            else:
                await query.edit_message_text(
                    "Chyba při rušení účasti.", reply_markup=None
                )
        except (IndexError, ValueError):
            logger.error(
                f"Neplatný cancel callback_data: {callback_data} pro user {user_id}"
            )
            await query.edit_message_text(
                "Chyba při zpracování volby.", reply_markup=None
            )
        except Exception as e:
            logger.error(
                f"Neočekávaná chyba handle_cancel_selection {callback_data} user {user_id}: {e}"
            )
            await query.message.reply_text("Neočekávaná chyba při rušení.")
    else:
        logger.warning(
            f"User {user_id} poslal neznámý cancel callback: {callback_data}"
        )
        await query.edit_message_text("Neznámá akce.", reply_markup=None)


# --- Handler pro neznámé zprávy ---
async def handle_unknown_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    # (kód handle_unknown_message zůstává stejný)
    text = update.message.text
    user_id = update.effective_user.id
    if "current_data_key" in context.user_data:
        logger.info(
            f"User {user_id} poslal '{text}' během sběru dat pro '{context.user_data['current_data_key']}'."
        )
        await update.message.reply_text(
            "Prosím, odpověz na položenou otázku nebo akci zruš příkazem /cancel."
        )
    else:
        logger.warning(
            f"Received unknown text message from {user_id} mimo konverzaci: {text}"
        )
        await update.message.reply_text(
            f"Promiň, na zprávu '{text}' neumím reagovat. Zkus /help."
        )


# --- Hlavní funkce ---
def main() -> None:
    """Spustí bota."""
    try:
        init_db()
    except Exception as e:
        logger.critical(
            f"Kritická chyba: Inicializace databáze selhala: {e}. Bot se nespustí."
        )
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_call_selection, pattern="^call_")],
        states={
            PROCESSING_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_data_input)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
        name="call_data_collection",
    )

    # Registrace handlerů
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("vyzvy", list_calls))
    application.add_handler(CommandHandler("zrusit_ucast", cancel_participation_start))
    application.add_handler(
        MessageHandler(
            filters.Regex("^(Ano, souhlasím 👍|Ne, děkuji)$"), handle_consent_response
        )
    )
    application.add_handler(
        CallbackQueryHandler(handle_cancel_selection, pattern="^cancel_")
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown_message)
    )

    logger.info("Spouštím bota (polling)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
