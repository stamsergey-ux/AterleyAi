"""Resource state assessment — voice-first, minimal."""
from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ChatAction
from sqlalchemy import select

from app.database import async_session, Member, Assessment
from app.keyboards import confirm_keyboard
from app.ai_service import text_to_speech
from app.voice_utils import store_voice_text, show_text_kb
from config import is_admin

router = Router()

# Conversational descriptions for each sphere
SPHERES = [
    {
        "key": "family_origin",
        "title": "Родительская семья",
        "intro": (
            "Первая сфера — родительская семья. "
            "Те, среди кого вы выросли.\n\n"
            "Насколько эта часть жизни вас наполняет?\n"
            "1 — забирает ресурс, 10 — даёт больше, чем вкладываете."
        ),
    },
    {
        "key": "family_own",
        "title": "Собственная семья",
        "intro": (
            "Ваша собственная семья или близкие отношения.\n\n"
            "Насколько эта сфера для вас ресурсна?\n"
            "1 — забирает, 10 — наполняет."
        ),
    },
    {
        "key": "life_fullness",
        "title": "Полнота жизни",
        "intro": (
            "Полнота жизни — хобби, друзья, путешествия, новый опыт.\n\n"
            "Насколько жизнь ощущается наполненной?\n"
            "1 — плоская, 10 — объёмная и цветная."
        ),
    },
    {
        "key": "realization",
        "title": "Реализация",
        "intro": (
            "Реализация — как профессионал, лидер, человек.\n\n"
            "Насколько вы реализованы?\n"
            "1 — не реализован, 10 — в полной мере."
        ),
    },
    {
        "key": "integration",
        "title": "Интеграция",
        "intro": (
            "Последний вопрос: всё, что происходит в вашей жизни — "
            "это для вас и вашего счастья?\n\n"
            "1 — живёте для кого-то другого, 10 — всё для вас."
        ),
    },
]


class AssessmentFSM(StatesGroup):
    answering = State()
    confirming = State()


def _score_buttons(sphere_index: int) -> list[list[InlineKeyboardButton]]:
    """Score buttons 1-10 as two rows of 5."""
    rows = []
    row = []
    for i in range(1, 11):
        row.append(InlineKeyboardButton(
            text=str(i),
            callback_data=f"score:{sphere_index}:{i}",
        ))
        if len(row) == 5:
            rows.append(row)
            row = []
    return rows


async def _send_voice_first(target, text: str, bot: Bot, chat_id: int,
                             extra_buttons: list | None = None, **kwargs):
    """Voice-first: voice without caption, text available via button.
    extra_buttons: rows of InlineKeyboardButton to prepend before 'Текст' button."""
    await bot.send_chat_action(chat_id, ChatAction.RECORD_VOICE)
    voice_bytes = await text_to_speech(text)

    if isinstance(target, CallbackQuery):
        answer_voice = target.message.answer_voice
        answer = target.message.answer
    else:
        answer_voice = target.answer_voice
        answer = target.answer

    if voice_bytes:
        key = store_voice_text(text)
        voice_file = BufferedInputFile(voice_bytes, filename="sphere.ogg")
        await answer_voice(
            voice_file,
            reply_markup=show_text_kb(key, extra_buttons),
        )
    else:
        # No voice — send text with buttons
        from app.keyboards import score_keyboard
        reply_markup = kwargs.get("reply_markup")
        await answer(text, reply_markup=reply_markup, **{k: v for k, v in kwargs.items() if k != "reply_markup"})


# ── Public functions for inline menu callbacks ───────────────────────────

async def start_assessment_flow(message: Message, state: FSMContext, bot: Bot):
    """Start assessment — called from menu callback or text command."""
    await state.set_state(AssessmentFSM.answering)
    await state.update_data(scores={}, current=0)

    sphere = SPHERES[0]
    text = f"Давайте начнём.\n\n{sphere['intro']}"

    await _send_voice_first(message, text, bot, message.chat.id,
                             extra_buttons=_score_buttons(0))


async def show_results_for_user(message: Message, bot: Bot, tg_id: int):
    """Show last assessment results."""
    async with async_session() as session:
        stmt = select(Member).where(Member.telegram_id == tg_id)
        result = await session.execute(stmt)
        member = result.scalar_one_or_none()

        if not member or not member.assessments:
            await message.answer(
                "У вас пока нет результатов. Просто скажите мне, когда будете готовы к оценке."
            )
            return

        last = sorted(member.assessments, key=lambda a: a.date, reverse=True)[0]
        scores = {
            "family_origin": last.family_origin,
            "family_own": last.family_own,
            "life_fullness": last.life_fullness,
            "realization": last.realization,
            "integration": last.integration,
        }
        summary = _format_summary(scores, last.average)
        total = len(member.assessments)

        text = (
            f"Результаты от {last.date.strftime('%d.%m.%Y')}:\n\n"
            f"{summary}\n\n"
            f"Всего оценок: {total}"
        )
        await message.answer(text, parse_mode="Markdown")


# ── Handlers ─────────────────────────────────────────────────────────────

@router.message(F.text == "📊 Пройти оценку")
async def start_assessment(message: Message, state: FSMContext, bot: Bot):
    await start_assessment_flow(message, state, bot)


@router.callback_query(F.data == "auto_start_assessment")
async def auto_start_assessment_cb(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Inline button triggered by AI suggestion — starts FULL assessment."""
    import logging
    logger = logging.getLogger(__name__)

    # Remove buttons from voice message (can't edit_text on voice)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()

    try:
        from app.handlers.full_assessment import start_full_assessment
        await start_full_assessment(callback.message, state, bot)
    except Exception as e:
        logger.exception("auto_start_assessment failed: %s", e)
        await bot.send_message(
            callback.from_user.id,
            f"Произошла ошибка при запуске оценки: {e}\nПопробуйте /menu → 🔬 Полная оценка",
        )


@router.callback_query(F.data.startswith("score:"))
async def process_score(callback: CallbackQuery, state: FSMContext, bot: Bot):
    _, sphere_idx_str, score_str = callback.data.split(":")
    sphere_idx = int(sphere_idx_str)
    score = int(score_str)

    data = await state.get_data()
    scores = data.get("scores", {})
    current_key = SPHERES[sphere_idx]["key"]
    scores[current_key] = score
    next_idx = sphere_idx + 1

    # Update button message with selected score
    await callback.message.edit_reply_markup(reply_markup=None)

    if next_idx < len(SPHERES):
        await state.update_data(scores=scores, current=next_idx)

        sphere = SPHERES[next_idx]
        await _send_voice_first(callback, sphere["intro"], bot,
                                 callback.from_user.id,
                                 extra_buttons=_score_buttons(next_idx))
    else:
        # All done — show compact results
        avg = sum(scores.values()) / len(scores)
        await state.update_data(scores=scores)
        await state.set_state(AssessmentFSM.confirming)

        summary = _format_summary(scores, avg)
        zone = _zone_label(avg)

        result_text = (
            f"Ваши результаты:\n\n"
            f"{summary}\n\n"
            f"Общее состояние — *{avg:.1f}/10* {zone}\n\n"
            "Подтвердить?"
        )

        # Results show as text (important to see), voice plays too
        await _send_voice_first(callback, result_text, bot,
                                 callback.from_user.id,
                                 extra_buttons=confirm_keyboard().inline_keyboard,
                                 parse_mode="Markdown")

    await callback.answer()


@router.callback_query(F.data == "confirm_assessment")
async def confirm_assessment(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    scores = data["scores"]
    avg = sum(scores.values()) / len(scores)

    tg_id = callback.from_user.id

    async with async_session() as session:
        stmt = select(Member).where(Member.telegram_id == tg_id)
        result = await session.execute(stmt)
        member = result.scalar_one_or_none()

        if member:
            assessment = Assessment(
                member_id=member.id,
                family_origin=scores.get("family_origin"),
                family_own=scores.get("family_own"),
                life_fullness=scores.get("life_fullness"),
                realization=scores.get("realization"),
                integration=scores.get("integration"),
                average=round(avg, 2),
            )
            session.add(assessment)
            await session.commit()

            # Store resource_id for full assessment flow
            await state.update_data(resource_assessment_id=assessment.id, resource_avg=round(avg, 2))

    await callback.message.edit_reply_markup(reply_markup=None)

    # Check if we're in a full assessment flow
    full_flow = data.get("full_flow", False)
    if full_flow:
        from app.handlers.full_assessment import after_resource_confirmed
        await after_resource_confirmed(callback, state, bot)
    else:
        await state.clear()
        farewell = "Спасибо за открытость. Если хотите поговорить — я здесь."
        await _send_voice_first(callback, farewell, bot, tg_id)

    await callback.answer()


@router.callback_query(F.data == "restart_assessment")
async def restart_assessment(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.set_state(AssessmentFSM.answering)
    await state.update_data(scores={}, current=0)

    sphere = SPHERES[0]
    text = f"Хорошо, начнём заново.\n\n{sphere['intro']}"

    await callback.message.edit_reply_markup(reply_markup=None)
    await _send_voice_first(callback, text, bot, callback.from_user.id,
                             extra_buttons=_score_buttons(0))
    await callback.answer()


@router.message(F.text == "📈 Мои результаты")
async def my_results(message: Message, bot: Bot):
    await show_results_for_user(message, bot, message.from_user.id)


# ── Compact result formatting ────────────────────────────────────────────

def _format_summary(scores: dict, avg: float) -> str:
    labels = {
        "family_origin": "Семья (род.)",
        "family_own": "Семья (своя)",
        "life_fullness": "Полнота жизни",
        "realization": "Реализация",
        "integration": "Интеграция",
    }
    lines = []
    for key, label in labels.items():
        val = scores.get(key, 0)
        indicator = _indicator(val)
        lines.append(f"{indicator} {label}: *{val}*/10")

    zone = _zone_label(avg)
    lines.append(f"\n*Среднее: {avg:.1f}/10* {zone}")
    return "\n".join(lines)


def _indicator(val: float) -> str:
    if val <= 3:
        return "🔴"
    elif val <= 5:
        return "🟡"
    elif val <= 7:
        return "🟢"
    return "💚"


def _zone_label(avg: float) -> str:
    if avg <= 3:
        return "— критическая зона"
    elif avg <= 5:
        return "— зона внимания"
    elif avg <= 7:
        return "— хорошо"
    else:
        return "— отлично"
