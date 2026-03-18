"""KPI module — view and manage team metrics."""
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session, Member
from config import is_admin

router = Router()


async def show_kpi_data(message: Message, username: str):
    """Show KPI — callable from inline menu."""
    if not is_admin(username):
        await message.answer("Доступ только для председателя и психолога.")
        return

    async with async_session() as session:
        stmt = (
            select(Member)
            .options(selectinload(Member.kpis), selectinload(Member.assessments))
            .order_by(Member.display_name)
        )
        result = await session.execute(stmt)
        members = result.scalars().all()

    if not members:
        await message.answer("Нет зарегистрированных участников.")
        return

    lines = ["📋 *KPI совета директоров*\n"]

    for m in members:
        # Resource state
        if m.assessments:
            last = sorted(m.assessments, key=lambda a: a.date, reverse=True)[0]
            resource = f"{last.average:.1f}/10"
            zone = _zone_emoji(last.average)
        else:
            resource = "—"
            zone = "⚪"

        lines.append(f"{zone} *{m.display_name}*")
        lines.append(f"  Ресурс: {resource}")

        if m.kpis:
            for kpi in m.kpis:
                progress = ""
                if kpi.value_target and kpi.value_target > 0:
                    pct = (kpi.value_current or 0) / kpi.value_target * 100
                    progress = f" ({pct:.0f}%)"
                lines.append(
                    f"  {kpi.metric_name}: "
                    f"{kpi.value_start or '—'} → "
                    f"*{kpi.value_current or '—'}* → "
                    f"{kpi.value_target or '—'}{progress}"
                )
                # Risk check
                if kpi.value_target and kpi.value_current:
                    remaining_growth = kpi.value_target / max(kpi.value_current, 0.01)
                    if remaining_growth > 2 and (last.average if m.assessments else 10) < 5:
                        lines.append(f"  ⚠️ _Нужен x{remaining_growth:.1f} рост при низком ресурсе_")
        else:
            lines.append("  KPI: не задан")

        lines.append("")

    await message.answer("\n".join(lines), parse_mode="Markdown")


def _zone_emoji(avg: float) -> str:
    if avg <= 3:
        return "🔴"
    elif avg <= 5:
        return "🟡"
    elif avg <= 7:
        return "🟢"
    return "💚"


@router.message(F.text == "📋 KPI команды")
async def show_kpi(message: Message):
    await show_kpi_data(message, message.from_user.username)
