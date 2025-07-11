import os
import logging
import tempfile
import mimetypes
from dotenv import load_dotenv
from telegram import Update, File as TelegramFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from telegram.error import BadRequest

from graph import app, new_chat, llm

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CHOOSING_LANGUAGE = 1
ALLOWED_MIME_TYPES = ["image/jpeg", "image/png"]
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation and asks for a language."""
    context.user_data.clear()
    context.user_data["from_start"] = True
    await update.message.reply_text(
        "Hello! Welcome to RIDA - Rice Disease AI Assistant developed by ThanksCarbon. 🌿\n\n"
        "To get started, please tell me which language you'd like me to use for our conversation and for the diagnostic reports.\n\n"
        "You can simply type the name of the language, for example:\n"
        "1. `English`\n"
        "2. `Khmer` or `ខ្មែរ`\n"
        "3. `Vietnamese` or `Tiếng Việt`.\n"
        "4. Or any other language\n\n"
        "I'll do my best to provide answers and reports in your chosen language!\n\n"
    )
    return CHOOSING_LANGUAGE


async def language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allows user to change language."""
    current_lang = context.user_data.get("language")
    if current_lang:
        await update.message.reply_text(
            f"Your current language is set to '{current_lang}'.\nWhat new language would you like to switch to?"
        )
    else:
        await update.message.reply_text("Sure, what language would you like to use?")
    return CHOOSING_LANGUAGE


async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sets the language for the conversation."""
    language = update.message.text

    checking_msg = await update.message.reply_text(
        f"Changing the assistant language to '{language}'..."
    )

    try:
        prompt = f"Can you generate text in the language '{language}'? Please answer with only 'yes' or 'no'."
        response = await llm.ainvoke(prompt)
        supported = "yes" in response.content.lower()
    except Exception as e:
        logging.error(f"Language check with LLM failed: {e}")
        supported = False

    if supported:
        context.user_data["language"] = language
        state = context.user_data.get("state", new_chat())
        state["language"] = language
        context.user_data["state"] = state

        user = update.effective_user

        confirmation_text_en = (
            f"Great! I will provide my answers and reports in {language}."
        )
        welcome_text_en_template = "Hi {user_mention}! I am RIDA - Rice Disease AI Assistant.\n\n📸 Send me a photo of a rice plant, and I'll analyze it for diseases and provide a detailed report.\n💬 You can ask me questions about a generated report or general questions about rice plant health."

        confirmation_text = confirmation_text_en
        welcome_text = welcome_text_en_template.format(
            user_mention=user.mention_markdown()
        )

        try:
            prompt = f"""You are a translation assistant. Translate the following text to {language}.
The text contains two parts separated by '|||'.
Preserve the '|||' separator in your output.
Preserve the `{{user_mention}}` placeholder in the second part.
Do not add any extra text or explanations.

Text to translate:
{confirmation_text_en}|||{welcome_text_en_template}
"""
            response = await llm.ainvoke(prompt)
            translations = response.content.split("|||")
            if len(translations) == 2:
                confirmation_text = translations[0].strip()
                translated_welcome_template = translations[1].strip()
                welcome_text = translated_welcome_template.replace(
                    "{user_mention}", user.mention_markdown()
                )
            else:
                logging.warning(
                    f"Could not parse translated messages, falling back to English. Response: {response.content}"
                )
        except Exception as e:
            logging.error(f"Failed to generate translated messages: {e}")

        await context.bot.edit_message_text(
            text=confirmation_text,
            chat_id=update.effective_chat.id,
            message_id=checking_msg.message_id,
        )
        if context.user_data.pop("from_start", False):
            await update.message.reply_markdown(welcome_text)

        return ConversationHandler.END
    else:
        await context.bot.edit_message_text(
            text=f"I'm sorry, but I might not be able to generate reports in language '{language}'. "
            "This could be due to a typo or it might be a language I don't fully support yet.\n\n"
            "Please try another language.",
            chat_id=update.effective_chat.id,
            message_id=checking_msg.message_id,
        )
        return CHOOSING_LANGUAGE


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current operation, like language selection."""
    await update.message.reply_text(
        "No problem! The language selection has been cancelled. How can I help you now?"
    )
    return ConversationHandler.END


async def send_or_edit_long_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    message_id: int,
) -> None:
    """
    Edits an existing message with the first part of the text.
    If the text is too long, it sends the remaining parts as new messages.
    """
    if not text:
        await context.bot.edit_message_text(
            text="Sorry, I couldn't generate a response.",
            chat_id=chat_id,
            message_id=message_id,
        )
        return

    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""
    for paragraph in paragraphs:
        while len(paragraph) > TELEGRAM_MAX_MESSAGE_LENGTH:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            split_pos = paragraph.rfind(" ", 0, TELEGRAM_MAX_MESSAGE_LENGTH)
            if split_pos == -1:
                split_pos = TELEGRAM_MAX_MESSAGE_LENGTH
            chunks.append(paragraph[:split_pos])
            paragraph = paragraph[split_pos:].lstrip()

        if len(current_chunk) + len(paragraph) + 2 > TELEGRAM_MAX_MESSAGE_LENGTH:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = paragraph
        else:
            if current_chunk:
                current_chunk += "\n\n"
            current_chunk += paragraph
    if current_chunk:
        chunks.append(current_chunk)

    if not chunks:
        await context.bot.edit_message_text(
            text="Sorry, I received an empty response.",
            chat_id=chat_id,
            message_id=message_id,
        )
        return

    try:
        await context.bot.edit_message_text(
            text=chunks[0],
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=None,
        )
    except BadRequest as e:
        if "entity" in str(e).lower():
            logging.warning(
                f"Markdown parse failed for chunk 0. Retrying without formatting. Error: {e}"
            )
            await context.bot.edit_message_text(
                text=chunks[0],
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=None,
            )
        else:
            raise e

    for i, chunk in enumerate(chunks[1:], 1):
        try:
            await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode=None)
        except BadRequest as e:
            if "entity" in str(e).lower():
                logging.warning(
                    f"Markdown parse failed for chunk {i}. Retrying without formatting. Error: {e}"
                )
                await context.bot.send_message(
                    chat_id=chat_id, text=chunk, parse_mode=None
                )
            else:
                raise e


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a help message when the /help command is issued."""
    help_text = (
        "Here's how I can help you:\n\n"
        "📸 Analyze a Photo\n"
        "Send me a photo of a rice plant, and I'll analyze it for diseases and provide a detailed report.\n\n"
        "💬 Ask a Question\n"
        "You can ask me questions about a report or general questions about rice plant health.\n\n"
        "Here are the available commands:\n"
        "1. /start - Start the bot.\n"
        "2. /language - Switch to a different language.\n"
        "3. /clear - Reset our conversation history.\n"
        "4. /help - Show this help message again.\n"
        "5. /cancel - Stop the language change operation."
    )
    await update.message.reply_text(help_text, parse_mode=None)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clears the conversation history, keeping the current language setting."""
    language = context.user_data.get("language")
    context.user_data.clear()

    if language:
        context.user_data["language"] = language
        state = new_chat()
        state["language"] = language
        context.user_data["state"] = state

        confirmation_text_en_template = "Done! Our conversation history has been cleared. I'm ready for new questions in {language}."

        try:
            prompt = f"You are a translation assistant. Translate the following text to {language}. Preserve the `{{language}}` placeholder. Do not add any extra text or explanations.\n\nText to translate:\n{confirmation_text_en_template}"
            response = await llm.ainvoke(prompt)
            translated_template = response.content.strip()
            confirmation_text = translated_template.replace("{language}", language)
        except Exception as e:
            logging.error(f"Failed to generate translated clear message: {e}")
            confirmation_text = confirmation_text_en_template.replace(
                "{language}", language
            )

        await update.message.reply_text(confirmation_text)
    else:
        await update.message.reply_text(
            "Our conversation history has been cleared. ✨\n"
            "Please use /start to begin a new conversation and set your language."
        )


async def _process_image(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_to_download: TelegramFile,
    mime_type: str,
    caption: str | None,
) -> None:
    """
    A helper function that handles the logic for processing an image.
    This includes downloading the file, calling the graph, and sending the response.
    """
    chat_id = update.message.chat_id
    thinking_message = await context.bot.send_message(
        chat_id, "Analyzing your image... 🔬"
    )

    temp_file_path = None
    try:
        suffix = mimetypes.guess_extension(mime_type) or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            await file_to_download.download_to_drive(temp_file.name)
            temp_file_path = temp_file.name

        with open(temp_file_path, "rb") as f:
            image_bytes = f.read()

        state = context.user_data.get("state", new_chat())

        report_id = context.user_data.get("report_id", 0) + 1
        context.user_data["report_id"] = report_id

        inputs = {
            "chat_history": state.get("chat_history", []),
            "question": caption or "",
            "image_bytes": image_bytes,
            "image_mime_type": mime_type,
            "language": context.user_data["language"],
            "report_id": report_id,
        }

        final_state = app.invoke(inputs)
        context.user_data["state"] = final_state
        final_answer = final_state.get(
            "generation", "Sorry, I couldn't analyze the image."
        )

        await send_or_edit_long_message(
            context, chat_id, final_answer, thinking_message.message_id
        )

        if report_id > 0 and report_id % 10 == 0:
            logging.info(
                f"Report ID {report_id} reached. Resetting memory for chat {chat_id}."
            )
            language = context.user_data.get("language")
            context.user_data.clear()

            if language:
                context.user_data["language"] = language
                state = new_chat()
                state["language"] = language
                context.user_data["state"] = state

                reset_message_en = "To keep our conversation fresh and accurate, I have automatically cleared our chat history. I'm ready for new questions!"
                reset_message = reset_message_en
                try:
                    prompt = f"You are a translation assistant. Translate the following text to {language}. Do not add any extra text or explanations.\n\nText to translate:\n{reset_message_en}"
                    response = await llm.ainvoke(prompt)
                    reset_message = response.content.strip()
                except Exception as e:
                    logging.error(f"Failed to generate translated reset message: {e}")

                await context.bot.send_message(chat_id, reset_message)

    except Exception as e:
        logging.error(f"An error occurred in _process_image: {e}")
        await context.bot.edit_message_text(
            text="I'm sorry, I encountered an issue while analyzing your image. It might be a temporary problem.\n\nCould you please try sending it again? If the issue persists, the file might be corrupted.",
            chat_id=chat_id,
            message_id=thinking_message.message_id,
        )
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles compressed photo uploads for disease analysis."""
    if "language" not in context.user_data:
        await update.message.reply_text(
            "Hello there! To get started, we first need to set a language.\n\n"
            "You can simply type the name of the language, for example:\n"
            "1. `English`\n"
            "2. `Khmer` or `ខ្មែរ`\n"
            "3. `Vietnamese` or `Tiếng Việt`.\n"
            "4. Or any other language\n"
            "I'll do my best to provide answers and reports in your chosen language!"
        )
        return

    photo_file = await update.message.photo[-1].get_file()
    await _process_image(
        update, context, photo_file, "image/jpeg", update.message.caption
    )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles file uploads (documents) and checks for allowed image types."""
    if "language" not in context.user_data:
        await update.message.reply_text(
            "Hello there! To get started, we first need to set a language.\n\n"
            "You can simply type the name of the language, for example:\n"
            "1. `English`\n"
            "2. `Khmer` or `ខ្មែរ`\n"
            "3. `Vietnamese` or `Tiếng Việt`.\n"
            "4. Or any other language\n"
            "I'll do my best to provide answers and reports in your chosen language!"
        )
        return

    document = update.message.document
    if document.mime_type not in ALLOWED_MIME_TYPES:
        allowed_formats = ", ".join(t.split("/")[1].upper() for t in ALLOWED_MIME_TYPES)
        await update.message.reply_text(
            f"Sorry, I can only analyze image files. The allowed formats are: {allowed_formats}.\n"
        )
        return

    file_to_download = await document.get_file()
    await _process_image(
        update, context, file_to_download, document.mime_type, update.message.caption
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles text messages for follow-up questions or general queries."""
    if "language" not in context.user_data:
        await update.message.reply_text(
            "Hello there! To get started, we first need to set a language.\n\n"
            "Please tap or type /start to begin."
        )
        return

    chat_id = update.message.chat_id
    thinking_message = await context.bot.send_message(chat_id, "Thinking... 🧠")

    try:
        state = context.user_data.get("state", new_chat())
        report_id = context.user_data.get("report_id", 0)
        question = update.message.text
        inputs = {
            "chat_history": state.get("chat_history", []),
            "question": question,
            "language": context.user_data["language"],
            "report_id": report_id,
        }
        final_state = app.invoke(inputs)
        context.user_data["state"] = final_state
        final_answer = final_state.get(
            "generation", "Sorry, I couldn't process your request."
        )

        await send_or_edit_long_message(
            context, chat_id, final_answer, thinking_message.message_id
        )

    except Exception as e:
        logging.error(f"An error occurred in handle_text: {e}")
        await context.bot.edit_message_text(
            text="I'm sorry, I'm having trouble processing your request right now. This could be a temporary issue on my end.\n\nPlease try asking again in a few moments.",
            chat_id=chat_id,
            message_id=thinking_message.message_id,
        )


def main() -> None:
    """Starts the bot."""
    logging.info("Starting bot...")
    if not TELEGRAM_BOT_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN not found in environment variables.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("language", language),
        ],
        states={
            CHOOSING_LANGUAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_language)
            ],
        },
        fallbacks=[
            CommandHandler("help", help_command),
            CommandHandler("clear", clear_command),
            CommandHandler("cancel", cancel),
        ],
        per_message=False,
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END,
        },
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    logging.info("Bot is running. Press Ctrl-C to stop.")
    application.run_polling()


if __name__ == "__main__":
    main()
