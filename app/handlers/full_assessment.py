"""Full assessment orchestrator: Motivation Map → Resource State → Needs Sphere → Derived Metrics."""
from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.enums import ChatAction
from sqlalchemy import select

from app.database import async_session, Member, DerivedMetrics
from app.ai_service import text_to_speech
from app.voice_utils import store_voice_text, show_text_kb

router = Router()


# ── Sociocultural levels (from doctor's PDF) ──────────────────────────────

SCU_LEVELS = [
    (1.0, 1.7, "Нулевой уровень",
     "Полная дезориентация. Человек не способен адекватно считывать ситуацию."),
    (1.8, 3.4, "Первый уровень — зависимый",
     "Зависимая позиция. Выживание. Мышление «свой-чужой». "
     "Импульсивные реакции, краткосрочное планирование."),
    (3.5, 5.1, "Второй уровень — конформный",
     "Стремление к принадлежности. Следование правилам и нормам группы. "
     "Важно одобрение, избегание конфликтов."),
    (5.2, 6.8, "Третий уровень — достижительный",
     "Ориентация на результат и личный успех. Конкуренция. "
     "Стратегическое мышление, амбиции, эффективность."),
    (6.9, 8.4, "Четвёртый уровень — постконвенциональный",
     "Системное мышление. Ценность отношений и развития. "
     "Баланс личного и командного, сотрудничество."),
    (8.5, 10.0, "Пятый уровень — интегральный",
     "Глобальное видение. Интеграция всех уровней. "
     "Способность преобразовывать среду, служение."),
]


def _get_scu_description(level: float) -> tuple[str, str]:
    """Return (level_name, description) for a given sociocultural level."""
    for low, high, name, desc in SCU_LEVELS:
        if low <= level <= high:
            return name, desc
    if level < 1.0:
        return SCU_LEVELS[0][2], SCU_LEVELS[0][3]
    return SCU_LEVELS[-1][2], SCU_LEVELS[-1][3]


# ── Life Energy interpretation ────────────────────────────────────────────

def _life_energy_interpretation(pct: float) -> str:
    if pct <= 30:
        return ("Не может быть социальным донором. "
                "Лидерство даётся непросто, переходит в жертвенность.")
    elif pct <= 64:
        return ("Достаточный уровень. Может быть социальным лидером. "
                "Важно следить за окружением — не допускать слишком много «рецепиентов».")
    else:
        return ("Избыточный уровень! Человек-аккумулятор. "
                "Способен преобразовывать ландшафт вокруг себя.")


# ── Action Potential interpretation ───────────────────────────────────────

def _action_potential_interpretation(pct: float) -> str:
    if pct <= 17:
        return ("Вектор — сохранение привычных границ области комфорта. "
                "Не выходит за привычные рамки.")
    elif pct <= 51:
        return ("Вектор — расширение области комфорта путём выхода за её границы. "
                "Присоединяет новые области.")
    else:
        return ("Вектор — диффузное расширение изнутри. "
                "Мастерски преобразует окружение, не выходя из области комфорта.")


# ── Color coding (doctor's scheme) ────────────────────────────────────────

def _color_indicator(val: float) -> str:
    """Universal color coding: ≤5.5 red, 5.6-8.0 yellow, >8.0 green."""
    if val <= 5.5:
        return "🔴"
    elif val <= 8.0:
        return "🟡"
    else:
        return "🟢"


# ── Public entry point ────────────────────────────────────────────────────

async def start_full_assessment(message: Message, state: FSMContext, bot: Bot):
    """Start the complete assessment flow: Motivation → Resource → Needs."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("start_full_assessment called, chat_id=%s", message.chat.id)

    # Mark that we're in full flow mode
    await state.update_data(full_flow=True)

    chat_id = message.chat.id

    text = (
        "Начинаем комплексное исследование.\n\n"
        "Мы пройдём три этапа:\n"
        "1️⃣ Карта мотивации\n"
        "2️⃣ Ресурсное состояние\n"
        "3️⃣ Потребностная сфера\n\n"
        "После чего рассчитаем ваши показатели. Начнём?"
    )

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    go_btn = [[InlineKeyboardButton(text="Начнём!", callback_data="full_assessment_go")]]

    try:
        await bot.send_chat_action(chat_id, ChatAction.RECORD_VOICE)
        voice_bytes = await text_to_speech(text)
    except Exception as e:
        logger.warning("TTS failed in start_full_assessment: %s", e)
        voice_bytes = b""

    if voice_bytes:
        key = store_voice_text(text)
        voice_file = BufferedInputFile(voice_bytes, filename="full_start.ogg")
        await bot.send_voice(chat_id, voice_file, reply_markup=show_text_kb(key, go_btn))
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=go_btn)
        await bot.send_message(chat_id, text, reply_markup=kb)


@router.callback_query(F.data == "full_assessment_go")
async def full_assessment_go(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.update_data(full_flow=True)

    # Start with motivation map
    from app.handlers.motivation import start_motivation_flow
    await start_motivation_flow(callback.message, state, bot)
    await callback.answer()


# ── Called after Resource State is confirmed (in full flow) ───────────────

async def after_resource_confirmed(callback_or_message, state: FSMContext, bot: Bot):
    """Transition from resource state to needs sphere in full flow."""
    tg_id = (callback_or_message.from_user.id
             if hasattr(callback_or_message, 'from_user')
             else callback_or_message.chat.id)

    chat_id = tg_id
    target = callback_or_message

    text = "Ресурсное состояние сохранено. Переходим к потребностной сфере."

    await bot.send_chat_action(chat_id, ChatAction.RECORD_VOICE)
    voice_bytes = await text_to_speech(text)
    if voice_bytes:
        key = store_voice_text(text)
        voice_file = BufferedInputFile(voice_bytes, filename="transition.ogg")
        if isinstance(target, CallbackQuery):
            await target.message.answer_voice(voice_file, reply_markup=show_text_kb(key))
        else:
            await target.answer_voice(voice_file, reply_markup=show_text_kb(key))

    # Start needs assessment
    from app.handlers.needs import start_needs_flow
    msg = target.message if isinstance(target, CallbackQuery) else target
    await start_needs_flow(msg, state, bot)


# ── Called after Needs Sphere is confirmed (final step) ───────────────────

async def finish_full_assessment(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Calculate derived metrics and show final results."""
    data = await state.get_data()
    tg_id = callback.from_user.id

    motivation_avg = data.get("motivation_avg", 0)
    resource_avg = data.get("resource_avg", 0)
    needs_avg = data.get("needs_avg", 0)

    # Derived calculations
    life_energy = resource_avg * needs_avg  # percentage (max 100)
    action_potential = (resource_avg * needs_avg * motivation_avg) / 10  # percentage
    scu = (resource_avg + needs_avg + motivation_avg) / 3
    stability = data.get("mot_stability", 5.0)

    # Save to DB
    async with async_session() as session:
        stmt = select(Member).where(Member.telegram_id == tg_id)
        result = await session.execute(stmt)
        member = result.scalar_one_or_none()

        if member:
            derived = DerivedMetrics(
                member_id=member.id,
                motivation_id=data.get("motivation_assessment_id"),
                resource_id=data.get("resource_assessment_id"),
                needs_id=data.get("needs_assessment_id"),
                motivation_avg=motivation_avg,
                resource_avg=resource_avg,
                needs_avg=needs_avg,
                life_energy=round(life_energy, 1),
                action_potential=round(action_potential, 1),
                sociocultural_level=round(scu, 1),
                behavior_stability=round(stability, 1),
            )
            session.add(derived)
            await session.commit()

    await state.clear()

    # Format comprehensive results
    scu_name, scu_desc = _get_scu_description(scu)
    le_interp = _life_energy_interpretation(life_energy)
    ap_interp = _action_potential_interpretation(action_potential)

    result_text = (
        "📊 *Комплексная оценка завершена!*\n\n"
        "*Три базовые оценки:*\n"
        f"{_color_indicator(motivation_avg)} Мотивация: *{motivation_avg:.1f}*/10\n"
        f"{_color_indicator(resource_avg)} Ресурс: *{resource_avg:.1f}*/10\n"
        f"{_color_indicator(needs_avg)} Потребности: *{needs_avg:.1f}*/10\n\n"
        "*Производные показатели:*\n"
        f"⚡ Жизненная энергия: *{life_energy:.1f}%*\n"
        f"   _{le_interp}_\n\n"
        f"🎯 Потенциал действия: *{action_potential:.1f}%*\n"
        f"   _{ap_interp}_\n\n"
        f"🏛 Социокультурный уровень: *{scu:.1f}*/10\n"
        f"   _{scu_name}_\n"
        f"   _{scu_desc}_\n\n"
        f"🔒 Стабильность поведения: *{stability:.1f}*/10\n"
    )

    await bot.send_chat_action(tg_id, ChatAction.RECORD_VOICE)
    voice_bytes = await text_to_speech(result_text.replace("*", "").replace("_", ""))

    if voice_bytes:
        key = store_voice_text(result_text)
        voice_file = BufferedInputFile(voice_bytes, filename="results.ogg")
        await callback.message.answer_voice(voice_file, reply_markup=show_text_kb(key))
    else:
        await callback.message.answer(result_text, parse_mode="Markdown")

    farewell = "Спасибо за открытость. Если хотите обсудить результаты — я здесь."
    await bot.send_chat_action(tg_id, ChatAction.RECORD_VOICE)
    voice_bytes2 = await text_to_speech(farewell)
    if voice_bytes2:
        key2 = store_voice_text(farewell)
        voice_file2 = BufferedInputFile(voice_bytes2, filename="farewell.ogg")
        await callback.message.answer_voice(voice_file2, reply_markup=show_text_kb(key2))
    else:
        await callback.message.answer(farewell)
