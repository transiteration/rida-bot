import os
import datetime
import logging
import json

STORAGE_DIR = "chat_logs"


def get_chat_storage_path(chat_id: int) -> str:
    """Returns the storage path for a given chat ID."""
    return os.path.join(STORAGE_DIR, str(chat_id))


def setup_storage(chat_id: int):
    """Sets up the storage directory for a chat."""
    chat_path = get_chat_storage_path(chat_id)
    os.makedirs(os.path.join(chat_path, "images"), exist_ok=True)


def _log_to_jsonl(log_path: str, data: dict):
    """Appends a JSON object to a JSONL file."""
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        logging.error(f"Failed to write to log file {log_path}: {e}")


def store_message(chat_id: int, user_name: str, text: str):
    """Stores a user's text message."""
    setup_storage(chat_id)
    log_path = os.path.join(get_chat_storage_path(chat_id), "conversation.jsonl")
    timestamp = datetime.datetime.now().isoformat()
    log_data = {
        "timestamp": timestamp,
        "sender": "user",
        "user_name": user_name,
        "type": "text",
        "content": text,
    }
    _log_to_jsonl(log_path, log_data)


def store_image(chat_id: int, user_name: str, image_path: str, caption: str | None):
    """Stores a reference to a user's image."""
    setup_storage(chat_id)
    log_path = os.path.join(get_chat_storage_path(chat_id), "conversation.jsonl")
    timestamp = datetime.datetime.now().isoformat()
    log_data = {
        "timestamp": timestamp,
        "sender": "user",
        "user_name": user_name,
        "type": "image",
        "image_path": os.path.basename(image_path),
        "caption": caption if caption else "",
    }
    _log_to_jsonl(log_path, log_data)


def store_bot_response(chat_id: int, text: str):
    """Stores the bot's response."""
    if not text:
        return
    setup_storage(chat_id)
    log_path = os.path.join(get_chat_storage_path(chat_id), "conversation.jsonl")
    timestamp = datetime.datetime.now().isoformat()
    log_data = {
        "timestamp": timestamp,
        "sender": "bot",
        "type": "text",
        "content": text,
    }
    _log_to_jsonl(log_path, log_data)