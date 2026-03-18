"""Free-form chat with AI psychologist — voice-first, text on demand."""
from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.enums import ChatAction

from app.ai_service import chat_response, transcribe_voice, text_to_speech
from app.keyboards import admin_menu_kb, member_menu_kb
from app.voice_utils import store_voice_text, get_voice_text, show_text_kb
from config import is_admin

router = Router()

# In-memory chat history per user (resets on restart)
_chat_history: dict[int, list[dict]] = {}
MAX_HISTORY = 20


async def _get_history(tg_id: int) -> list[dict]:
    return _chat_history.get(tg_id, [])


async def _save_message(tg_id: int, role: str, content: str):
    if tg_id not in _chat_history:
        _chat_history[tg_id] = []
    _chat_history[tg_id].append({"role": role, "content": content})
    if len(_chat_history[tg_id]) > MAX_HISTORY:
        _chat_history[tg_id] = _chat_history[tg_id][-MAX_HISTORY:]


async def _send_voice_first(message: Message, bot: Bot, text: str,
                             extra_buttons: list | None = None):
    """Voice-first: send voice message without caption, text available via button."""
    tg_id = message.chat.id

    await bot.send_chat_action(tg_id, ChatAction.RECORD_VOICE)
    voice_bytes = await text_to_speech(text)

    if voice_bytes:
        key = store_voice_text(text)
        voice_file = BufferedInputFile(voice_bytes, filename="response.ogg")
        await message.answer_voice(
            voice_file,
            reply_markup=show_text_kb(key, extra_buttons),
        )
    else:
        # No voice — fall back to text
        await message.answer(text)


async def _process_ai_response(message: Message, bot: Bot, tg_id: int, user_text: str,
                                state: FSMContext | None = None):
    """Get AI response, detect [НАЧАТЬ_ОЦЕНКУ], respond with voice."""
    import logging
    logger = logging.getLogger(__name__)

    history = await _get_history(tg_id)
    await _save_message(tg_id, "user", user_text)

    response_text = await chat_response(user_text, history)

    # Check if AI wants to start assessment
    trigger = "[НАЧАТЬ_ОЦЕНКУ]"
    if trigger in response_text:
        clean_text = response_text.replace(trigger, "").strip()
        await _save_message(tg_id, "assistant", clean_text)

        # Send AI response first, then auto-start assessment
        await _send_voice_first(message, bot, clean_text)

        if state:
            try:
                from app.handlers.full_assessment import start_full_assessment
                await start_full_assessment(message, state, bot)
            except Exception as e:
                logger.exception("Auto-start assessment failed: %s", e)
                await bot.send_message(tg_id, "Попробуйте /menu → 🔬 Полная оценка")
        else:
            # Fallback: show button if state not available
            extra = [[InlineKeyboardButton(text="Начать оценку", callback_data="auto_start_assessment")]]
            await bot.send_message(
                tg_id, "Для начала оценки нажмите кнопку:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=extra),
            )
        return

    await _save_message(tg_id, "assistant", response_text)
    await _send_voice_first(message, bot, response_text)


# ── Show text callback (shared across all handlers) ──────────────────────

@router.callback_query(F.data.startswith("vt:"))
async def show_voice_text_cb(callback: CallbackQuery):
    """Show text transcript of a voice message."""
    key = callback.data[3:]
    text = get_voice_text(key)
    if text:
        await callback.message.answer(text)
    else:
        await callback.message.answer("Текст недоступен.")
    await callback.answer()


# ── /menu command — inline menu ──────────────────────────────────────────

@router.message(F.text == "/menu")
async def cmd_menu(message: Message):
    username = message.from_user.username
    kb = admin_menu_kb() if is_admin(username) else member_menu_kb()
    await message.answer("Меню:", reply_markup=kb)


@router.callback_query(F.data == "cmd_assessment")
async def cb_assessment(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.edit_text("Начинаем оценку...")
    await callback.answer()
    from app.handlers.assessment import start_assessment_flow
    await start_assessment_flow(callback.message, state, bot)


@router.callback_query(F.data == "cmd_results")
async def cb_results(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    from app.handlers.assessment import show_results_for_user
    await show_results_for_user(callback.message, bot, callback.from_user.id)


@router.callback_query(F.data == "cmd_heatmap")
async def cb_heatmap(callback: CallbackQuery):
    await callback.answer()
    from app.handlers.heatmap import show_heatmap_data
    await show_heatmap_data(callback.message, callback.from_user.username)


@router.callback_query(F.data == "cmd_kpi")
async def cb_kpi(callback: CallbackQuery):
    await callback.answer()
    from app.handlers.kpi import show_kpi_data
    await show_kpi_data(callback.message, callback.from_user.username)


@router.callback_query(F.data == "cmd_diary")
async def cb_diary(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from app.handlers.notes import show_diary_menu
    await show_diary_menu(callback.message, state, callback.from_user.username)


@router.callback_query(F.data == "cmd_admin")
async def cb_admin(callback: CallbackQuery):
    await callback.answer()
    from app.handlers.admin import show_admin_info
    await show_admin_info(callback.message, callback.from_user.username)


@router.callback_query(F.data == "cmd_full_assessment")
async def cb_full_assessment(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.edit_text("Начинаем комплексное исследование...")
    await callback.answer()
    from app.handlers.full_assessment import start_full_assessment
    await start_full_assessment(callback.message, state, bot)


@router.callback_query(F.data == "cmd_motivation")
async def cb_motivation(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.edit_text("Начинаем карту мотивации...")
    await callback.answer()
    from app.handlers.motivation import start_motivation_flow
    await start_motivation_flow(callback.message, state, bot)


@router.callback_query(F.data == "cmd_needs")
async def cb_needs(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.edit_text("Начинаем оценку потребностей...")
    await callback.answer()
    from app.handlers.needs import start_needs_flow
    await start_needs_flow(callback.message, state, bot)


# ── Voice handler ────────────────────────────────────────────────────────

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, state: FSMContext):
    tg_id = message.from_user.id

    current_state = await state.get_state()
    if current_state is not None:
        return

    await bot.send_chat_action(tg_id, ChatAction.TYPING)

    file = await bot.get_file(message.voice.file_id)
    audio_data = await bot.download_file(file.file_path)
    audio_bytes = audio_data.read()

    text = await transcribe_voice(audio_bytes)
    if not text:
        await message.answer("Простите, не удалось расслышать. Попробуйте ещё раз.")
        return

    await message.answer(f"_«{text}»_", parse_mode="Markdown")
    await _process_ai_response(message, bot, tg_id, text, state=state)


# ── Text handler (catch-all, must be last router) ────────────────────────

@router.message(F.text)
async def handle_text(message: Message, state: FSMContext, bot: Bot):
    if message.text.startswith("/"):
        return

    current_state = await state.get_state()
    if current_state is not None:
        return

    tg_id = message.from_user.id
    await _process_ai_response(message, bot, tg_id, message.text, state=state)
