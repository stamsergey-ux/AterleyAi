from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import Message, BufferedInputFile
from aiogram.enums import ChatAction
from sqlalchemy import select

from app.database import async_session, Member, KPI
from app.keyboards import remove_kb
from app.ai_service import text_to_speech
from app.voice_utils import store_voice_text, show_text_kb
from config import is_admin, BOARD_MEMBERS

router = Router()

WELCOME_TEXT_NEW = (
    "Здравствуйте, {name}. Я Aterley, ваш психолог.\n\n"
    "Можем общаться текстом или голосом — как удобнее."
)

WELCOME_TEXT_RETURN = (
    "Рад вас снова видеть, {name}. Как вы себя чувствуете сегодня?"
)


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    username = message.from_user.username
    tg_id = message.from_user.id
    first_name = message.from_user.first_name or message.from_user.full_name

    is_new = False
    async with async_session() as session:
        stmt = select(Member).where(Member.telegram_id == tg_id)
        result = await session.execute(stmt)
        member = result.scalar_one_or_none()

        if not member:
            is_new = True
            display = first_name
            kpi_name = None
            for bm in BOARD_MEMBERS:
                if bm["username"] and username and bm["username"].lower() == username.lower():
                    display = bm["display_name"]
                    kpi_name = bm.get("kpi")
                    break

            member = Member(
                telegram_id=tg_id,
                username=username,
                display_name=display,
            )
            session.add(member)
            await session.flush()

            if kpi_name:
                kpi = KPI(
                    member_id=member.id,
                    metric_name=kpi_name,
                    value_start=0,
                    value_current=0,
                    value_target=0,
                )
                session.add(kpi)

            await session.commit()

    if is_new:
        welcome = WELCOME_TEXT_NEW.format(name=first_name)
    else:
        welcome = WELCOME_TEXT_RETURN.format(name=first_name)

    # Voice-first: voice without caption, text via button
    await bot.send_chat_action(tg_id, ChatAction.RECORD_VOICE)
    voice_bytes = await text_to_speech(welcome)
    if voice_bytes:
        key = store_voice_text(welcome)
        voice_file = BufferedInputFile(voice_bytes, filename="greeting.ogg")
        await message.answer_voice(voice_file, reply_markup=show_text_kb(key))
    else:
        await message.answer(welcome, reply_markup=remove_kb)
