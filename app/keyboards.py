from aiogram.types import (
    ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
)


# ── Remove reply keyboard ─────────────────────────────────────────────────
remove_kb = ReplyKeyboardRemove()


# ── Inline keyboards ────────────────────────────────────────────────────────

def admin_menu_kb() -> InlineKeyboardMarkup:
    """Inline admin menu for chairman / psychologist."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔬 Полная оценка", callback_data="cmd_full_assessment"),
        ],
        [
            InlineKeyboardButton(text="📊 Ресурс", callback_data="cmd_assessment"),
            InlineKeyboardButton(text="🧠 Мотивация", callback_data="cmd_motivation"),
            InlineKeyboardButton(text="💡 Потребности", callback_data="cmd_needs"),
        ],
        [
            InlineKeyboardButton(text="📈 Результаты", callback_data="cmd_results"),
            InlineKeyboardButton(text="🗺 Тепловая карта", callback_data="cmd_heatmap"),
        ],
        [
            InlineKeyboardButton(text="📋 KPI", callback_data="cmd_kpi"),
            InlineKeyboardButton(text="📝 Дневник", callback_data="cmd_diary"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Управление", callback_data="cmd_admin"),
        ],
    ])


def member_menu_kb() -> InlineKeyboardMarkup:
    """Inline menu for regular members."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔬 Полная оценка", callback_data="cmd_full_assessment"),
        ],
        [
            InlineKeyboardButton(text="📊 Ресурс", callback_data="cmd_assessment"),
            InlineKeyboardButton(text="📈 Результаты", callback_data="cmd_results"),
        ],
    ])


def score_keyboard(sphere_index: int) -> InlineKeyboardMarkup:
    """1-10 score buttons for a sphere."""
    buttons = []
    row = []
    for i in range(1, 11):
        row.append(InlineKeyboardButton(
            text=str(i),
            callback_data=f"score:{sphere_index}:{i}",
        ))
        if len(row) == 5:
            buttons.append(row)
            row = []
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def member_select_keyboard(members: list[dict], action: str) -> InlineKeyboardMarkup:
    """Select a board member (for notes, KPI view, etc.)."""
    buttons = []
    for m in members:
        label = m["display_name"]
        member_id = m["id"]
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"{action}:{member_id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Подтвердить", callback_data="confirm_assessment"),
            InlineKeyboardButton(text="Заново", callback_data="restart_assessment"),
        ]
    ])
