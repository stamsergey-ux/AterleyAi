"""Heat map — board overview for chairman / psychologist."""
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session, Member, Assessment
from config import is_admin

router = Router()


def _ci(val: float) -> str:
    """Color indicator: ≤5.5 red, 5.6-8.0 yellow, >8.0 green."""
    if val <= 5.5:
        return "🔴"
    elif val <= 8.0:
        return "🟡"
    return "🟢"


async def show_heatmap_data(message: Message, username: str):
    """Show heatmap — callable from inline menu."""
    if not is_admin(username):
        await message.answer("Доступ только для председателя и психолога.")
        return

    async with async_session() as session:
        stmt = (
            select(Member)
            .options(
                selectinload(Member.assessments),
                selectinload(Member.kpis),
                selectinload(Member.motivation_assessments),
                selectinload(Member.needs_assessments),
                selectinload(Member.derived_metrics),
            )
            .order_by(Member.display_name)
        )
        result = await session.execute(stmt)
        members = result.scalars().all()

    if not members:
        await message.answer("Нет зарегистрированных участников.")
        return

    # ── Resource State table ──────────────────────────────
    lines = ["🗺 *Тепловая карта совета директоров*\n"]
    lines.append("*Ресурсное состояние:*")
    lines.append("```")
    lines.append(f"{'Имя':<16} {'Сем1':>4} {'Сем2':>4} {'Жиз':>4} {'Реал':>4} {'Инт':>4} {'Ср':>5}")
    lines.append("─" * 48)

    for m in members:
        if m.assessments:
            last = sorted(m.assessments, key=lambda a: a.date, reverse=True)[0]
            vals = [
                last.family_origin or 0, last.family_own or 0,
                last.life_fullness or 0, last.realization or 0,
                last.integration or 0,
            ]
            avg = last.average or 0
            vals_str = " ".join(f"{v:4.0f}" for v in vals)
            avg_str = f"{avg:5.1f}"
        else:
            vals_str = "   —    —    —    —    —"
            avg_str = "   — "

        name = m.display_name[:16]
        lines.append(f"{name:<16} {vals_str} {avg_str}")

    lines.append("```")

    # ── Comprehensive metrics table ───────────────────────
    has_derived = any(m.derived_metrics for m in members)
    if has_derived:
        lines.append("\n*Комплексная оценка:*")
        lines.append("```")
        lines.append(f"{'Имя':<16} {'Мот':>4} {'Рес':>4} {'Потр':>4} {'ЖЭ':>5} {'ПД':>5} {'СКУ':>4}")
        lines.append("─" * 48)

        for m in members:
            if m.derived_metrics:
                last_d = sorted(m.derived_metrics, key=lambda d: d.date, reverse=True)[0]
                mot = last_d.motivation_avg or 0
                res = last_d.resource_avg or 0
                needs = last_d.needs_avg or 0
                le = last_d.life_energy or 0
                ap = last_d.action_potential or 0
                scu = last_d.sociocultural_level or 0
                lines.append(
                    f"{m.display_name[:16]:<16} {mot:4.1f} {res:4.1f} {needs:4.1f} "
                    f"{le:4.0f}% {ap:4.0f}% {scu:4.1f}"
                )
            else:
                lines.append(f"{m.display_name[:16]:<16}    —    —    —    —     —    —")

        lines.append("```")
        lines.append("_Мот=Мотивация Рес=Ресурс Потр=Потребности ЖЭ=Жизн.энергия ПД=Потенциал СКУ=Социокульт.уровень_")

    # ── Risk alerts ───────────────────────────────────────
    alerts = _find_risks(members)
    if alerts:
        lines.append("\n⚠️ *Зоны риска:*")
        for alert in alerts:
            lines.append(f"• {alert}")

    await message.answer("\n".join(lines), parse_mode="Markdown")


def _find_risks(members: list[Member]) -> list[str]:
    """Identify members in risk zones across all metrics."""
    alerts = []
    for m in members:
        # Resource state risks
        if m.assessments:
            last = sorted(m.assessments, key=lambda a: a.date, reverse=True)[0]
            avg = last.average or 0

            if avg <= 4.2:
                alerts.append(f"🔴 {m.display_name} — ресурс {avg:.1f}, зависимая позиция")
            elif avg <= 5.5:
                alerts.append(f"🟡 {m.display_name} — ресурс {avg:.1f}, зона внимания")

            for attr, label in [
                ("family_origin", "Род. семья"),
                ("family_own", "Своя семья"),
                ("life_fullness", "Полнота жизни"),
                ("realization", "Реализация"),
                ("integration", "Интеграция"),
            ]:
                val = getattr(last, attr) or 0
                if val <= 2 and avg > 3:
                    alerts.append(f"⚡ {m.display_name} — {label}: {val:.0f}/10")

        # Motivation risks
        if m.motivation_assessments:
            last_m = sorted(m.motivation_assessments, key=lambda a: a.date, reverse=True)[0]
            sat = last_m.overall_satisfaction or 0
            if sat <= 4.2:
                alerts.append(f"🔴 {m.display_name} — мотивация {sat:.1f}, срыв вероятен")
            elif sat <= 5.5:
                alerts.append(f"🟡 {m.display_name} — мотивация {sat:.1f}, неустойчивость")

        # Derived metrics risks
        if m.derived_metrics:
            last_d = sorted(m.derived_metrics, key=lambda d: d.date, reverse=True)[0]
            le = last_d.life_energy or 0
            if le <= 30:
                alerts.append(f"🔴 {m.display_name} — жизн. энергия {le:.0f}%, не может быть донором")

    return alerts


@router.message(F.text == "🗺 Тепловая карта")
async def show_heatmap(message: Message):
    await show_heatmap_data(message, message.from_user.username)
