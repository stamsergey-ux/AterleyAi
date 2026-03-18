"""Admin panel — settings and management for chairman / psychologist."""
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from app.database import async_session, Member
from config import is_admin

router = Router()


async def show_admin_info(message: Message, username: str):
    """Show admin info — callable from inline menu."""
    if not is_admin(username):
        await message.answer("Доступ только для председателя и психолога.")
        return

    async with async_session() as session:
        stmt = select(Member)
        result = await session.execute(stmt)
        members = result.scalars().all()

    text = (
        "⚙️ *Управление*\n\n"
        f"Участников: {len(members)}\n\n"
        "/list — список участников\n"
        "/menu — главное меню"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(F.text == "⚙️ Управление")
async def admin_menu(message: Message):
    await show_admin_info(message, message.from_user.username)


@router.message(F.text == "/list")
async def list_members(message: Message):
    username = message.from_user.username
    if not is_admin(username):
        return

    async with async_session() as session:
        stmt = select(Member).order_by(Member.display_name)
        result = await session.execute(stmt)
        members = result.scalars().all()

    if not members:
        await message.answer("Нет зарегистрированных участников.")
        return

    lines = ["*Участники:*\n"]
    for i, m in enumerate(members, 1):
        username_str = f"@{m.username}" if m.username else "—"
        assessments_count = len(m.assessments) if m.assessments else 0
        lines.append(f"{i}. {m.display_name} ({username_str}) — оценок: {assessments_count}")

    await message.answer("\n".join(lines), parse_mode="Markdown")
