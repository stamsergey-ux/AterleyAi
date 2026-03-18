"""Voice-first UX — store text for voice messages, show on demand."""
from __future__ import annotations

import uuid

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# In-memory storage: key → text (for "show text" button)
_voice_texts: dict[str, str] = {}


def store_voice_text(text: str) -> str:
    """Store text and return a short key for callback_data."""
    key = uuid.uuid4().hex[:8]
    _voice_texts[key] = text
    # Keep max 200 entries
    if len(_voice_texts) > 200:
        oldest = next(iter(_voice_texts))
        del _voice_texts[oldest]
    return key


def get_voice_text(key: str) -> str | None:
    return _voice_texts.get(key)


def show_text_kb(key: str, extra_buttons: list | None = None) -> InlineKeyboardMarkup:
    """Inline keyboard with '📝 Текст' button + optional extra buttons."""
    rows = []
    if extra_buttons:
        rows.extend(extra_buttons)
    rows.append([InlineKeyboardButton(text="📝 Текст", callback_data=f"vt:{key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
