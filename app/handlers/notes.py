"""Psychologist's diary — notes per member."""
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from app.database import async_session, Member, PsychologistNote
from app.keyboards import member_select_keyboard
from config import is_admin

router = Router()


class NoteFSM(StatesGroup):
    selecting_member = State()
    writing_note = State()
    viewing = State()


async def show_diary_menu(message: Message, state: FSMContext, username: str):
    """Show diary menu — callable from inline menu."""
    if not is_admin(username):
        await message.answer("Доступ только для психолога и председателя.")
        return

    async with async_session() as session:
        stmt = select(Member).order_by(Member.display_name)
        result = await session.execute(stmt)
        members = result.scalars().all()

    if not members:
        await message.answer("Нет зарегистрированных участников.")
        return

    member_list = [{"id": m.id, "display_name": m.display_name} for m in members]
    await state.set_state(NoteFSM.selecting_member)
    await message.answer(
        "📝 *Дневник психолога*\n\nВыберите участника:",
        reply_markup=member_select_keyboard(member_list, "diary_member"),
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("diary_member:"))
async def select_member(callback: CallbackQuery, state: FSMContext):
    member_id = int(callback.data.split(":")[1])
    await state.update_data(member_id=member_id)

    async with async_session() as session:
        stmt = select(Member).where(Member.id == member_id)
        result = await session.execute(stmt)
        member = result.scalar_one_or_none()

        notes_stmt = (
            select(PsychologistNote)
            .where(PsychologistNote.member_id == member_id)
            .order_by(PsychologistNote.created_at.desc())
            .limit(10)
        )
        notes_result = await session.execute(notes_stmt)
        notes = notes_result.scalars().all()

    text = f"📝 *{member.display_name}*\n\n"
    if notes:
        for n in reversed(notes):
            date_str = n.created_at.strftime("%d.%m.%Y %H:%M")
            text += f"_{date_str}_\n{n.text}\n\n"
    else:
        text += "Заметок пока нет.\n\n"

    text += "Отправьте текст, чтобы добавить заметку, или /cancel для отмены."

    await state.set_state(NoteFSM.writing_note)
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()


@router.message(NoteFSM.writing_note, F.text)
async def save_note(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return

    data = await state.get_data()
    member_id = data["member_id"]

    async with async_session() as session:
        note = PsychologistNote(
            member_id=member_id,
            author_username=message.from_user.username,
            text=message.text,
        )
        session.add(note)
        await session.commit()

    await message.answer(
        "Заметка сохранена. Отправьте ещё или /cancel для выхода."
    )


@router.message(F.text == "📝 Дневник")
async def diary_menu(message: Message, state: FSMContext):
    await show_diary_menu(message, state, message.from_user.username)
