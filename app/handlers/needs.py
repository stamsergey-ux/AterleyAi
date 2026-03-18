"""Needs sphere assessment — 5 spheres, reverse logic (1=satisfied, 10=strongly needed)."""
from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ChatAction
from sqlalchemy import select

from app.database import async_session, Member, NeedsAssessment
from app.keyboards import confirm_keyboard
from app.ai_service import text_to_speech
from app.voice_utils import store_voice_text, show_text_kb

router = Router()

NEEDS_SPHERES = [
    {
        "key": "mental",
        "title": "Ментальная сфера",
        "intro": (
            "Ментальные потребности — работа головой, новые знания, "
            "обучение, наставничество, создание интеллектуальных продуктов, "
            "рефлексия, любопытство.\n\n"
            "Насколько сейчас выражена эта потребность?\n"
            "1 — всего достаточно, 10 — остро не хватает."
        ),
    },
    {
        "key": "social",
        "title": "Социальная сфера",
        "intro": (
            "Социальные потребности — отношения, принадлежность к группе, "
            "статус, власть, влияние, карьера, межличностные связи.\n\n"
            "Насколько выражена потребность?\n"
            "1 — всего достаточно, 10 — остро хочется."
        ),
    },
    {
        "key": "emotional",
        "title": "Эмоциональная сфера",
        "intro": (
            "Эмоциональные потребности — возможность спонтанно выражать "
            "и получать эмоции, наблюдать за эмоциями других.\n\n"
            "Насколько выражена потребность?\n"
            "1 — всего достаточно, 10 — остро чувствуете нехватку."
        ),
    },
    {
        "key": "spiritual",
        "title": "Духовная сфера",
        "intro": (
            "Духовные потребности — ценностная реализация, смысл жизни, "
            "вера, свобода, любовь, гармония с собой и миром.\n\n"
            "Насколько выражена потребность?\n"
            "1 — живёте в ладу с собой, 10 — остро хотите переделать."
        ),
    },
    {
        "key": "physical",
        "title": "Физическая сфера",
        "intro": (
            "Физические потребности — безопасность, сон, еда, комфорт, "
            "здоровье, спорт, физическая активность.\n\n"
            "Насколько выражена потребность?\n"
            "1 — всего достаточно, 10 — хочется в полной мере."
        ),
    },
]


class NeedsFSM(StatesGroup):
    answering = State()
    confirming = State()


def _needs_score_buttons(sphere_index: int) -> list[list[InlineKeyboardButton]]:
    rows = []
    row = []
    for i in range(1, 11):
        row.append(InlineKeyboardButton(
            text=str(i),
            callback_data=f"nscore:{sphere_index}:{i}",
        ))
        if len(row) == 5:
            rows.append(row)
            row = []
    return rows


def _needs_confirm_kb() -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(text="Подтвердить", callback_data="confirm_needs"),
            InlineKeyboardButton(text="Заново", callback_data="restart_needs"),
        ]
    ]


async def _send_voice_first(target, text: str, bot: Bot, chat_id: int,
                             extra_buttons: list | None = None, **kwargs):
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
        voice_file = BufferedInputFile(voice_bytes, filename="needs.ogg")
        await answer_voice(voice_file, reply_markup=show_text_kb(key, extra_buttons))
    else:
        reply_markup = kwargs.get("reply_markup")
        await answer(text, reply_markup=reply_markup,
                     **{k: v for k, v in kwargs.items() if k != "reply_markup"})


# ── Public entry point ────────────────────────────────────────────────────

async def start_needs_flow(message: Message, state: FSMContext, bot: Bot):
    """Start needs assessment — called from menu or full assessment flow."""
    await state.set_state(NeedsFSM.answering)
    await state.update_data(needs_scores={}, needs_current=0)

    sphere = NEEDS_SPHERES[0]
    text = (
        "Теперь оценим потребностную сферу.\n\n"
        "Здесь логика обратная: 1 — потребность закрыта, "
        "10 — ярко выражена, очень не хватает.\n\n"
        f"{sphere['intro']}"
    )
    await _send_voice_first(message, text, bot, message.chat.id,
                             extra_buttons=_needs_score_buttons(0))


async def show_needs_results(message: Message, bot: Bot, tg_id: int):
    """Show last needs assessment results."""
    async with async_session() as session:
        stmt = select(Member).where(Member.telegram_id == tg_id)
        result = await session.execute(stmt)
        member = result.scalar_one_or_none()

        if not member or not member.needs_assessments:
            await message.answer("У вас пока нет результатов по потребностной сфере.")
            return

        last = sorted(member.needs_assessments, key=lambda a: a.date, reverse=True)[0]
        scores = {
            "mental": last.mental,
            "social": last.social,
            "emotional": last.emotional,
            "spiritual": last.spiritual,
            "physical": last.physical,
        }
        summary = _format_needs_summary(scores, last.average)
        text = (
            f"Потребностная сфера от {last.date.strftime('%d.%m.%Y')}:\n\n"
            f"{summary}"
        )
        await message.answer(text, parse_mode="Markdown")


# ── Handlers ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("nscore:"))
async def process_needs_score(callback: CallbackQuery, state: FSMContext, bot: Bot):
    _, sphere_idx_str, score_str = callback.data.split(":")
    sphere_idx = int(sphere_idx_str)
    score = int(score_str)

    data = await state.get_data()
    scores = data.get("needs_scores", {})
    current_key = NEEDS_SPHERES[sphere_idx]["key"]
    scores[current_key] = score
    next_idx = sphere_idx + 1

    await callback.message.edit_reply_markup(reply_markup=None)

    if next_idx < len(NEEDS_SPHERES):
        await state.update_data(needs_scores=scores, needs_current=next_idx)
        sphere = NEEDS_SPHERES[next_idx]
        await _send_voice_first(callback, sphere["intro"], bot,
                                 callback.from_user.id,
                                 extra_buttons=_needs_score_buttons(next_idx))
    else:
        avg = sum(scores.values()) / len(scores)
        await state.update_data(needs_scores=scores)
        await state.set_state(NeedsFSM.confirming)

        summary = _format_needs_summary(scores, avg)
        zone = _needs_zone_label(avg)

        result_text = (
            f"Потребностная сфера:\n\n"
            f"{summary}\n\n"
            f"Среднее — *{avg:.1f}/10* {zone}\n\n"
            "Подтвердить?"
        )
        await _send_voice_first(callback, result_text, bot,
                                 callback.from_user.id,
                                 extra_buttons=_needs_confirm_kb(),
                                 parse_mode="Markdown")

    await callback.answer()


@router.callback_query(F.data == "confirm_needs")
async def confirm_needs(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    scores = data["needs_scores"]
    avg = sum(scores.values()) / len(scores)
    tg_id = callback.from_user.id

    async with async_session() as session:
        stmt = select(Member).where(Member.telegram_id == tg_id)
        result = await session.execute(stmt)
        member = result.scalar_one_or_none()

        if member:
            needs = NeedsAssessment(
                member_id=member.id,
                mental=scores.get("mental"),
                social=scores.get("social"),
                emotional=scores.get("emotional"),
                spiritual=scores.get("spiritual"),
                physical=scores.get("physical"),
                average=round(avg, 2),
            )
            session.add(needs)
            await session.commit()

            # Store needs_id for full assessment flow
            await state.update_data(needs_assessment_id=needs.id, needs_avg=round(avg, 2))

    await callback.message.edit_reply_markup(reply_markup=None)

    # Check if we're in a full assessment flow
    full_flow = data.get("full_flow", False)
    if full_flow:
        # Proceed to derived calculations
        from app.handlers.full_assessment import finish_full_assessment
        await finish_full_assessment(callback, state, bot)
    else:
        await state.clear()
        farewell = "Оценка потребностной сферы завершена. Спасибо!"
        await _send_voice_first(callback, farewell, bot, tg_id)

    await callback.answer()


@router.callback_query(F.data == "restart_needs")
async def restart_needs(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    # Preserve full_flow flag and other assessment data
    preserved = {k: v for k, v in data.items() if not k.startswith("needs_")}
    preserved["needs_scores"] = {}
    preserved["needs_current"] = 0
    await state.update_data(**preserved)
    await state.set_state(NeedsFSM.answering)

    sphere = NEEDS_SPHERES[0]
    text = f"Хорошо, начнём заново.\n\n{sphere['intro']}"

    await callback.message.edit_reply_markup(reply_markup=None)
    await _send_voice_first(callback, text, bot, callback.from_user.id,
                             extra_buttons=_needs_score_buttons(0))
    await callback.answer()


# ── Formatting ────────────────────────────────────────────────────────────

def _format_needs_summary(scores: dict, avg: float) -> str:
    labels = {
        "mental": "Ментальная",
        "social": "Социальная",
        "emotional": "Эмоциональная",
        "spiritual": "Духовная",
        "physical": "Физическая",
    }
    lines = []
    for key, label in labels.items():
        val = scores.get(key, 0)
        indicator = _needs_indicator(val)
        lines.append(f"{indicator} {label}: *{val}*/10")

    zone = _needs_zone_label(avg)
    lines.append(f"\n*Среднее: {avg:.1f}/10* {zone}")
    return "\n".join(lines)


def _needs_indicator(val: float) -> str:
    """Reverse logic: low = satisfied (green), high = needy (red)."""
    if val <= 3:
        return "💚"
    elif val <= 5:
        return "🟢"
    elif val <= 7:
        return "🟡"
    return "🔴"


def _needs_zone_label(avg: float) -> str:
    """Reverse: low avg = needs satisfied, high = acute needs."""
    if avg <= 3:
        return "— потребности закрыты"
    elif avg <= 5:
        return "— умеренные потребности"
    elif avg <= 7:
        return "— выраженные потребности"
    else:
        return "— острые потребности"
