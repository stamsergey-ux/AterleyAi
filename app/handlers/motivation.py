"""Motivation Map — multi-step conversational assessment of work satisfaction factors."""
from __future__ import annotations

import re
from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, BufferedInputFile,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ChatAction
from sqlalchemy import select

from app.database import async_session, Member, MotivationAssessment, MotivationFactor
from app.ai_service import text_to_speech, transcribe_voice
from app.voice_utils import store_voice_text, show_text_kb

router = Router()


class MotivationFSM(StatesGroup):
    listing_factors = State()          # User lists factors
    confirming_factors = State()       # Confirm factor list
    describing_factor = State()        # Describe current factor
    money_q1 = State()                 # Деньги: satisfied?
    money_q2 = State()                 # Деньги: increase?
    money_q3 = State()                 # Деньги: meaning?
    rating_importance = State()        # Rate importance per factor (buttons)
    prioritizing = State()             # Rank factors with same importance
    rating_satisfaction = State()      # Rate satisfaction per factor (buttons)
    openness = State()                 # Openness scale
    confirming_results = State()       # Review and confirm


# ── Voice-first helper ────────────────────────────────────────────────────

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
        voice_file = BufferedInputFile(voice_bytes, filename="motivation.ogg")
        await answer_voice(voice_file, reply_markup=show_text_kb(key, extra_buttons))
    else:
        reply_markup = kwargs.get("reply_markup")
        await answer(text, reply_markup=reply_markup,
                     **{k: v for k, v in kwargs.items() if k != "reply_markup"})


def _score_buttons(prefix: str, index: int) -> list[list[InlineKeyboardButton]]:
    """1-10 buttons with custom prefix."""
    rows = []
    row = []
    for i in range(1, 11):
        row.append(InlineKeyboardButton(
            text=str(i), callback_data=f"{prefix}:{index}:{i}",
        ))
        if len(row) == 5:
            rows.append(row)
            row = []
    return rows


def _parse_factors(text: str) -> list[str]:
    """Parse comma/newline-separated factor list from user input."""
    # Split by commas, newlines, semicolons, or numbered list patterns
    raw = re.split(r'[,;\n]+|\d+[.)]\s*', text)
    factors = []
    for f in raw:
        f = f.strip().strip("-•").strip()
        if f and len(f) > 1:
            factors.append(f.capitalize())
    return factors


# ── Public entry point ────────────────────────────────────────────────────

async def start_motivation_flow(message: Message, state: FSMContext, bot: Bot):
    """Start motivation map — called from menu or full assessment flow."""
    await state.set_state(MotivationFSM.listing_factors)
    await state.update_data(
        mot_factors=[],      # list of factor names
        mot_descs={},        # factor -> description
        mot_importance={},   # factor -> importance score
        mot_satisfaction={}, # factor -> satisfaction score
        mot_priority={},     # factor -> priority rank
        mot_money={},        # money Q1/Q2/Q3
        mot_openness=None,
        mot_desc_idx=0,      # current factor being described
        mot_imp_idx=0,       # current factor for importance
        mot_sat_idx=0,       # current factor for satisfaction
        mot_prio_group=[],   # factors to prioritize
        mot_prio_rank=1,     # current priority rank being assigned
    )

    text = (
        "Начнём с карты мотивации.\n\n"
        "Назовите факторы, которые важны для вас в работе. "
        "Например: деньги, команда, график, престиж компании, "
        "полномочия, личность руководителя...\n\n"
        "Перечислите через запятую или голосовым сообщением. "
        "Факторов может быть сколь угодно много."
    )
    await _send_voice_first(message, text, bot, message.chat.id)


# ── Step 1: Factor listing ────────────────────────────────────────────────

@router.message(MotivationFSM.listing_factors, F.voice)
async def factors_voice(message: Message, state: FSMContext, bot: Bot):
    file = await bot.get_file(message.voice.file_id)
    audio_data = await bot.download_file(file.file_path)
    text = await transcribe_voice(audio_data.read())
    if not text:
        await message.answer("Не удалось расслышать, попробуйте ещё раз.")
        return
    await message.answer(f"_«{text}»_", parse_mode="Markdown")
    await _process_factor_list(message, state, bot, text)


@router.message(MotivationFSM.listing_factors, F.text)
async def factors_text(message: Message, state: FSMContext, bot: Bot):
    await _process_factor_list(message, state, bot, message.text)


async def _process_factor_list(message: Message, state: FSMContext, bot: Bot, text: str):
    factors = _parse_factors(text)
    if not factors:
        await message.answer("Не удалось распознать факторы. Перечислите их через запятую.")
        return

    # Ensure "Деньги" is always present
    has_money = any("деньг" in f.lower() for f in factors)
    if not has_money:
        factors.append("Деньги")

    await state.update_data(mot_factors=factors)

    factor_list = "\n".join(f"  {i+1}. {f}" for i, f in enumerate(factors))
    confirm_text = (
        f"Ваши факторы:\n{factor_list}\n\n"
        "Всё верно? Или хотите добавить/убрать?"
    )
    buttons = [
        [
            InlineKeyboardButton(text="Всё верно", callback_data="mot_factors_ok"),
            InlineKeyboardButton(text="Заново", callback_data="mot_factors_redo"),
        ]
    ]
    await _send_voice_first(message, confirm_text, bot, message.chat.id,
                             extra_buttons=buttons)
    await state.set_state(MotivationFSM.confirming_factors)


@router.callback_query(F.data == "mot_factors_redo")
async def redo_factors(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(MotivationFSM.listing_factors)
    await _send_voice_first(
        callback, "Хорошо, перечислите факторы заново.", bot, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "mot_factors_ok")
async def confirm_factors(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.edit_reply_markup(reply_markup=None)
    data = await state.get_data()
    factors = data["mot_factors"]

    # Start describing factors
    await state.update_data(mot_desc_idx=0)
    await state.set_state(MotivationFSM.describing_factor)

    factor = factors[0]
    is_money = "деньг" in factor.lower()

    if is_money:
        # Money has special questions first
        await state.set_state(MotivationFSM.money_q1)
        text = (
            f"Фактор «{factor}».\n\n"
            "Первый вопрос: довольны ли вы сейчас своим совокупным доходом в компании?"
        )
    else:
        text = (
            f"Фактор «{factor}».\n\n"
            "Что этот фактор значит для вас в идеале? "
            "Опишите коротко — текстом или голосом."
        )
    await _send_voice_first(callback, text, bot, callback.from_user.id)
    await callback.answer()


# ── Step 2: Factor descriptions ───────────────────────────────────────────

@router.message(MotivationFSM.describing_factor, F.voice)
async def desc_voice(message: Message, state: FSMContext, bot: Bot):
    file = await bot.get_file(message.voice.file_id)
    audio_data = await bot.download_file(file.file_path)
    text = await transcribe_voice(audio_data.read())
    if not text:
        await message.answer("Не удалось расслышать, попробуйте ещё раз.")
        return
    await message.answer(f"_«{text}»_", parse_mode="Markdown")
    await _save_description_and_advance(message, state, bot, text)


@router.message(MotivationFSM.describing_factor, F.text)
async def desc_text(message: Message, state: FSMContext, bot: Bot):
    await _save_description_and_advance(message, state, bot, message.text)


async def _save_description_and_advance(message: Message, state: FSMContext,
                                         bot: Bot, description: str):
    data = await state.get_data()
    factors = data["mot_factors"]
    idx = data["mot_desc_idx"]
    descs = data.get("mot_descs", {})

    descs[factors[idx]] = description
    next_idx = idx + 1
    await state.update_data(mot_descs=descs, mot_desc_idx=next_idx)

    # Move to next factor
    if next_idx < len(factors):
        factor = factors[next_idx]
        is_money = "деньг" in factor.lower()

        if is_money:
            await state.set_state(MotivationFSM.money_q1)
            text = (
                f"Фактор «{factor}».\n\n"
                "Первый вопрос: довольны ли вы сейчас своим совокупным доходом?"
            )
        else:
            text = (
                f"Фактор «{factor}».\n\n"
                "Что этот фактор значит для вас в идеале?"
            )
        await _send_voice_first(message, text, bot, message.chat.id)
    else:
        # All described — move to importance rating
        await _start_importance_phase(message, state, bot)


# ── Money special questions ───────────────────────────────────────────────

@router.message(MotivationFSM.money_q1, F.voice)
async def money_q1_voice(message: Message, state: FSMContext, bot: Bot):
    file = await bot.get_file(message.voice.file_id)
    audio_data = await bot.download_file(file.file_path)
    text = await transcribe_voice(audio_data.read())
    if text:
        await message.answer(f"_«{text}»_", parse_mode="Markdown")
        await _process_money_q1(message, state, bot, text)

@router.message(MotivationFSM.money_q1, F.text)
async def money_q1_text(message: Message, state: FSMContext, bot: Bot):
    await _process_money_q1(message, state, bot, message.text)

async def _process_money_q1(message, state, bot, answer):
    data = await state.get_data()
    money = data.get("mot_money", {})
    money["satisfied"] = answer
    await state.update_data(mot_money=money)
    await state.set_state(MotivationFSM.money_q2)
    text = "Хотели бы увеличения дохода? Если да — на сколько процентов или во сколько раз?"
    await _send_voice_first(message, text, bot, message.chat.id)


@router.message(MotivationFSM.money_q2, F.voice)
async def money_q2_voice(message: Message, state: FSMContext, bot: Bot):
    file = await bot.get_file(message.voice.file_id)
    audio_data = await bot.download_file(file.file_path)
    text = await transcribe_voice(audio_data.read())
    if text:
        await message.answer(f"_«{text}»_", parse_mode="Markdown")
        await _process_money_q2(message, state, bot, text)

@router.message(MotivationFSM.money_q2, F.text)
async def money_q2_text(message: Message, state: FSMContext, bot: Bot):
    await _process_money_q2(message, state, bot, message.text)

async def _process_money_q2(message, state, bot, answer):
    data = await state.get_data()
    money = data.get("mot_money", {})
    money["increase"] = answer
    await state.update_data(mot_money=money)
    await state.set_state(MotivationFSM.money_q3)
    text = "Что для вас деньги вообще, как фактор? Что они означают?"
    await _send_voice_first(message, text, bot, message.chat.id)


@router.message(MotivationFSM.money_q3, F.voice)
async def money_q3_voice(message: Message, state: FSMContext, bot: Bot):
    file = await bot.get_file(message.voice.file_id)
    audio_data = await bot.download_file(file.file_path)
    text = await transcribe_voice(audio_data.read())
    if text:
        await message.answer(f"_«{text}»_", parse_mode="Markdown")
        await _process_money_q3(message, state, bot, text)

@router.message(MotivationFSM.money_q3, F.text)
async def money_q3_text(message: Message, state: FSMContext, bot: Bot):
    await _process_money_q3(message, state, bot, message.text)

async def _process_money_q3(message, state, bot, answer):
    data = await state.get_data()
    money = data.get("mot_money", {})
    money["meaning"] = answer
    descs = data.get("mot_descs", {})
    # Store money meaning as description for the Деньги factor
    factors = data["mot_factors"]
    money_factor = next((f for f in factors if "деньг" in f.lower()), "Деньги")
    descs[money_factor] = f"Доволен доходом: {money.get('satisfied', '')}. " \
                          f"Увеличение: {money.get('increase', '')}. " \
                          f"Значение: {answer}"
    await state.update_data(mot_money=money, mot_descs=descs)

    # Move to next factor description or to importance phase
    idx = data["mot_desc_idx"]
    next_idx = idx + 1
    await state.update_data(mot_desc_idx=next_idx)

    if next_idx < len(factors):
        factor = factors[next_idx]
        is_money = "деньг" in factor.lower()
        if is_money:
            await state.set_state(MotivationFSM.money_q1)
            text = f"Фактор «{factor}».\nДовольны ли вы сейчас своим совокупным доходом?"
        else:
            await state.set_state(MotivationFSM.describing_factor)
            text = f"Фактор «{factor}».\nЧто этот фактор значит для вас в идеале?"
        await _send_voice_first(message, text, bot, message.chat.id)
    else:
        await _start_importance_phase(message, state, bot)


# ── Step 3: Importance rating ─────────────────────────────────────────────

async def _start_importance_phase(message: Message, state: FSMContext, bot: Bot):
    await state.set_state(MotivationFSM.rating_importance)
    await state.update_data(mot_imp_idx=0)

    data = await state.get_data()
    factor = data["mot_factors"][0]
    text = (
        "Отлично! Теперь оцените важность каждого фактора.\n\n"
        f"Фактор «{factor}» — насколько важен?\n"
        "1 — практически не важен, 10 — важен в полной мере."
    )
    await _send_voice_first(message, text, bot, message.chat.id,
                             extra_buttons=_score_buttons("mimp", 0))


@router.callback_query(F.data.startswith("mimp:"))
async def process_importance(callback: CallbackQuery, state: FSMContext, bot: Bot):
    _, idx_str, score_str = callback.data.split(":")
    idx = int(idx_str)
    score = int(score_str)

    data = await state.get_data()
    factors = data["mot_factors"]
    importance = data.get("mot_importance", {})
    importance[factors[idx]] = score
    next_idx = idx + 1

    await callback.message.edit_reply_markup(reply_markup=None)

    if next_idx < len(factors):
        await state.update_data(mot_importance=importance, mot_imp_idx=next_idx)
        factor = factors[next_idx]
        text = f"Фактор «{factor}» — насколько важен? (1-10)"
        await _send_voice_first(callback, text, bot, callback.from_user.id,
                                 extra_buttons=_score_buttons("mimp", next_idx))
    else:
        await state.update_data(mot_importance=importance)
        # Move to prioritization
        await _start_priority_phase(callback, state, bot)

    await callback.answer()


# ── Step 4: Prioritization ────────────────────────────────────────────────

async def _start_priority_phase(target, state: FSMContext, bot: Bot):
    """Build priority ranking. Group by importance, ask user to rank within ties."""
    data = await state.get_data()
    factors = data["mot_factors"]
    importance = data["mot_importance"]

    # Sort factors by importance descending
    sorted_factors = sorted(factors, key=lambda f: importance.get(f, 0), reverse=True)

    # Auto-assign priority for unique importance values
    priority = {}
    rank = 1
    groups = {}
    for f in sorted_factors:
        imp = importance.get(f, 0)
        if imp not in groups:
            groups[imp] = []
        groups[imp].append(f)

    # Find ties that need resolution
    ties_to_resolve = []
    for imp in sorted(groups.keys(), reverse=True):
        group = groups[imp]
        if len(group) > 1:
            ties_to_resolve.append((imp, group))
        else:
            priority[group[0]] = rank
        rank += len(group)

    if ties_to_resolve:
        # Need user input to break ties
        imp, group = ties_to_resolve[0]
        await state.update_data(
            mot_priority=priority,
            mot_prio_ties=ties_to_resolve,
            mot_prio_tie_idx=0,
            mot_prio_within=[],
            mot_prio_rank=len(priority) + 1,
        )
        await state.set_state(MotivationFSM.prioritizing)

        text = (
            f"У вас несколько факторов с важностью {imp}:\n"
            + "\n".join(f"  • {f}" for f in group) +
            "\n\nКакой из них на первом месте?"
        )
        buttons = [[InlineKeyboardButton(
            text=f, callback_data=f"mprio:{i}"
        )] for i, f in enumerate(group)]

        chat_id = target.from_user.id if isinstance(target, CallbackQuery) else target.chat.id
        await _send_voice_first(target, text, bot, chat_id, extra_buttons=buttons)
    else:
        # No ties — auto-assign priorities
        rank = 1
        for f in sorted_factors:
            priority[f] = rank
            rank += 1
        await state.update_data(mot_priority=priority)
        await _start_satisfaction_phase(target, state, bot)


@router.callback_query(F.data.startswith("mprio:"))
async def process_priority(callback: CallbackQuery, state: FSMContext, bot: Bot):
    chosen_idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    ties = data["mot_prio_ties"]
    tie_idx = data["mot_prio_tie_idx"]
    within = data.get("mot_prio_within", [])
    priority = data["mot_priority"]
    rank = data["mot_prio_rank"]

    imp, group = ties[tie_idx]
    chosen = group[chosen_idx]
    priority[chosen] = rank
    within.append(chosen)

    await callback.message.edit_reply_markup(reply_markup=None)

    remaining = [f for f in group if f not in within]

    if len(remaining) > 1:
        # More to rank in this group
        await state.update_data(
            mot_priority=priority,
            mot_prio_within=within,
            mot_prio_rank=rank + 1,
        )
        text = f"Хорошо. Из оставшихся — какой следующий?"
        buttons = [[InlineKeyboardButton(
            text=f, callback_data=f"mprio:{group.index(f)}"
        )] for f in remaining]
        await _send_voice_first(callback, text, bot, callback.from_user.id,
                                 extra_buttons=buttons)
    elif len(remaining) == 1:
        # Last one gets auto-assigned
        priority[remaining[0]] = rank + 1
        within.append(remaining[0])

        # Check next tie group
        next_tie_idx = tie_idx + 1
        if next_tie_idx < len(ties):
            imp2, group2 = ties[next_tie_idx]
            await state.update_data(
                mot_priority=priority,
                mot_prio_tie_idx=next_tie_idx,
                mot_prio_within=[],
                mot_prio_rank=rank + 2,
            )
            text = (
                f"У вас также факторы с важностью {imp2}:\n"
                + "\n".join(f"  • {f}" for f in group2) +
                "\n\nКакой на первом месте?"
            )
            buttons = [[InlineKeyboardButton(
                text=f, callback_data=f"mprio:{i}"
            )] for i, f in enumerate(group2)]
            await _send_voice_first(callback, text, bot, callback.from_user.id,
                                     extra_buttons=buttons)
        else:
            await state.update_data(mot_priority=priority)
            await _start_satisfaction_phase(callback, state, bot)
    else:
        await state.update_data(mot_priority=priority)
        next_tie_idx = tie_idx + 1
        if next_tie_idx < len(ties):
            imp2, group2 = ties[next_tie_idx]
            await state.update_data(
                mot_prio_tie_idx=next_tie_idx,
                mot_prio_within=[],
                mot_prio_rank=rank + 1,
            )
            text = f"Факторы с важностью {imp2} — какой важнее?"
            buttons = [[InlineKeyboardButton(
                text=f, callback_data=f"mprio:{i}"
            )] for i, f in enumerate(group2)]
            await _send_voice_first(callback, text, bot, callback.from_user.id,
                                     extra_buttons=buttons)
        else:
            await _start_satisfaction_phase(callback, state, bot)

    await callback.answer()


# ── Step 5: Satisfaction rating ───────────────────────────────────────────

async def _start_satisfaction_phase(target, state: FSMContext, bot: Bot):
    await state.set_state(MotivationFSM.rating_satisfaction)
    await state.update_data(mot_sat_idx=0)

    data = await state.get_data()
    factor = data["mot_factors"][0]
    text = (
        "Теперь оцените удовлетворённость каждым фактором "
        "на текущий момент.\n\n"
        f"Фактор «{factor}» — насколько довольны сейчас?\n"
        "1 — практически не доволен, 10 — доволен в полной мере."
    )
    chat_id = target.from_user.id if isinstance(target, CallbackQuery) else target.chat.id
    await _send_voice_first(target, text, bot, chat_id,
                             extra_buttons=_score_buttons("msat", 0))


@router.callback_query(F.data.startswith("msat:"))
async def process_satisfaction(callback: CallbackQuery, state: FSMContext, bot: Bot):
    _, idx_str, score_str = callback.data.split(":")
    idx = int(idx_str)
    score = int(score_str)

    data = await state.get_data()
    factors = data["mot_factors"]
    satisfaction = data.get("mot_satisfaction", {})
    satisfaction[factors[idx]] = score
    next_idx = idx + 1

    await callback.message.edit_reply_markup(reply_markup=None)

    if next_idx < len(factors):
        await state.update_data(mot_satisfaction=satisfaction, mot_sat_idx=next_idx)
        factor = factors[next_idx]
        text = f"Фактор «{factor}» — насколько довольны? (1-10)"
        await _send_voice_first(callback, text, bot, callback.from_user.id,
                                 extra_buttons=_score_buttons("msat", next_idx))
    else:
        await state.update_data(mot_satisfaction=satisfaction)
        # Move to openness
        await state.set_state(MotivationFSM.openness)
        text = (
            "Последний вопрос по карте мотивации.\n\n"
            "Оцените свою откровенность в этом исследовании:\n"
            "1 — почему-то был закрыт, 10 — был спонтанно откровенен."
        )
        await _send_voice_first(callback, text, bot, callback.from_user.id,
                                 extra_buttons=_score_buttons("mopen", 0))

    await callback.answer()


# ── Step 6: Openness ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("mopen:"))
async def process_openness(callback: CallbackQuery, state: FSMContext, bot: Bot):
    _, _, score_str = callback.data.split(":")
    openness = int(score_str)

    await callback.message.edit_reply_markup(reply_markup=None)
    await state.update_data(mot_openness=openness)

    # Calculate results
    data = await state.get_data()
    factors = data["mot_factors"]
    importance = data["mot_importance"]
    satisfaction = data["mot_satisfaction"]
    priority = data.get("mot_priority", {})

    # Overall satisfaction = average of satisfaction scores
    sat_values = [satisfaction.get(f, 0) for f in factors]
    overall_sat = sum(sat_values) / len(sat_values) if sat_values else 0

    # Behavior stability: check gaps in high-priority factors
    stability = _calc_stability(factors, importance, satisfaction, priority)

    await state.update_data(
        mot_overall_satisfaction=round(overall_sat, 2),
        mot_stability=round(stability, 2),
    )
    await state.set_state(MotivationFSM.confirming_results)

    summary = _format_motivation_summary(
        factors, importance, satisfaction, priority,
        overall_sat, stability, openness,
    )
    result_text = (
        f"Карта мотивации:\n\n{summary}\n\n"
        "Подтвердить?"
    )
    buttons = [
        [
            InlineKeyboardButton(text="Подтвердить", callback_data="confirm_motivation"),
            InlineKeyboardButton(text="Заново", callback_data="restart_motivation"),
        ]
    ]
    await _send_voice_first(callback, result_text, bot, callback.from_user.id,
                             extra_buttons=buttons, parse_mode="Markdown")
    await callback.answer()


# ── Confirm / Restart ─────────────────────────────────────────────────────

@router.callback_query(F.data == "confirm_motivation")
async def confirm_motivation(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    factors = data["mot_factors"]
    importance = data["mot_importance"]
    satisfaction = data["mot_satisfaction"]
    priority = data.get("mot_priority", {})
    descs = data.get("mot_descs", {})
    money = data.get("mot_money", {})
    openness = data.get("mot_openness", 5)
    overall_sat = data["mot_overall_satisfaction"]
    stability = data["mot_stability"]

    tg_id = callback.from_user.id

    async with async_session() as session:
        stmt = select(Member).where(Member.telegram_id == tg_id)
        result = await session.execute(stmt)
        member = result.scalar_one_or_none()

        if member:
            assessment = MotivationAssessment(
                member_id=member.id,
                overall_satisfaction=overall_sat,
                openness=openness,
                behavior_stability=stability,
            )
            session.add(assessment)
            await session.flush()

            for f in factors:
                is_money = "деньг" in f.lower()
                factor_obj = MotivationFactor(
                    assessment_id=assessment.id,
                    name=f,
                    description=descs.get(f, ""),
                    importance=importance.get(f),
                    priority_rank=priority.get(f),
                    satisfaction=satisfaction.get(f),
                    money_satisfied=money.get("satisfied") if is_money else None,
                    money_increase=money.get("increase") if is_money else None,
                    money_meaning=money.get("meaning") if is_money else None,
                )
                session.add(factor_obj)

            await session.commit()

            # Store motivation_id for full assessment flow
            await state.update_data(
                motivation_assessment_id=assessment.id,
                motivation_avg=overall_sat,
            )

    await callback.message.edit_reply_markup(reply_markup=None)

    # Check if we're in a full assessment flow
    full_flow = data.get("full_flow", False)
    if full_flow:
        # Proceed to resource state assessment
        from app.handlers.assessment import start_assessment_flow
        text = "Карта мотивации сохранена. Переходим к ресурсному состоянию."
        await _send_voice_first(callback, text, bot, tg_id)
        await start_assessment_flow(callback.message, state, bot)
    else:
        await state.clear()
        farewell = "Карта мотивации завершена. Спасибо за открытость!"
        await _send_voice_first(callback, farewell, bot, tg_id)

    await callback.answer()


@router.callback_query(F.data == "restart_motivation")
async def restart_motivation(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    full_flow = data.get("full_flow", False)
    await state.clear()
    if full_flow:
        await state.update_data(full_flow=True)
    await callback.message.edit_reply_markup(reply_markup=None)
    await start_motivation_flow(callback.message, state, bot)
    await callback.answer()


# ── Calculations ──────────────────────────────────────────────────────────

def _calc_stability(factors, importance, satisfaction, priority) -> float:
    """Calculate behavior stability based on importance-satisfaction gaps.

    High importance + low satisfaction in top-priority factors = low stability.
    Returns value 1-10 where 10 = very stable.
    """
    if not factors:
        return 5.0

    gaps = []
    for f in factors:
        imp = importance.get(f, 5)
        sat = satisfaction.get(f, 5)
        prio = priority.get(f, len(factors))
        # Weight gap by importance and priority (lower rank = more important)
        weight = imp / 10 * (1 + (len(factors) - prio) / len(factors))
        gap = max(0, imp - sat) * weight
        gaps.append(gap)

    max_possible_gap = sum(
        (10 / 10) * (1 + (len(factors) - i) / len(factors)) * 10
        for i in range(1, len(factors) + 1)
    )
    total_gap = sum(gaps)

    if max_possible_gap == 0:
        return 10.0

    # Invert: 0 gap = 10 stability, max gap = 1 stability
    stability = 10.0 - (total_gap / max_possible_gap) * 9.0
    return max(1.0, min(10.0, stability))


def _format_motivation_summary(factors, importance, satisfaction, priority,
                                overall_sat, stability, openness) -> str:
    """Format motivation map results."""
    # Sort by priority
    sorted_f = sorted(factors, key=lambda f: priority.get(f, 99))

    lines = []
    for f in sorted_f:
        imp = importance.get(f, 0)
        sat = satisfaction.get(f, 0)
        prio = priority.get(f, "—")
        gap = imp - sat
        indicator = "🔴" if gap >= 4 else ("🟡" if gap >= 2 else "🟢")
        lines.append(f"{indicator} #{prio} {f}: важн.*{imp}* / удовл.*{sat}*")

    lines.append(f"\n*Удовлетворённость: {overall_sat:.1f}/10* {_zone(overall_sat)}")
    lines.append(f"*Стабильность: {stability:.1f}/10*")
    lines.append(f"*Откровенность: {openness}/10*")
    return "\n".join(lines)


def _zone(val: float) -> str:
    if val <= 4.2:
        return "— зависимая позиция (срыв)"
    elif val <= 5.5:
        return "— переходная зона"
    elif val <= 8.0:
        return "— независимая позиция"
    else:
        return "— устойчивая позиция"
