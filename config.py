from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAIRMAN_USERNAMES = [
    u.strip().lower()
    for u in os.getenv("CHAIRMAN_USERNAMES", "").split(",")
    if u.strip()
]
PSYCHOLOGIST_USERNAMES = [
    u.strip().lower()
    for u in os.getenv("PSYCHOLOGIST_USERNAMES", "").split(",")
    if u.strip()
]

_raw_db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data.db")
# Railway gives postgresql:// — SQLAlchemy async needs postgresql+asyncpg://
if _raw_db_url.startswith("postgresql://"):
    _raw_db_url = _raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _raw_db_url.startswith("postgres://"):
    _raw_db_url = _raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
DATABASE_URL = _raw_db_url
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")


def is_chairman(username: str | None) -> bool:
    return bool(username and username.lower() in CHAIRMAN_USERNAMES)


def is_psychologist(username: str | None) -> bool:
    return bool(username and username.lower() in PSYCHOLOGIST_USERNAMES)


def is_admin(username: str | None) -> bool:
    return is_chairman(username) or is_psychologist(username)


# Board members — will be confirmed/updated by chairman
BOARD_MEMBERS = [
    {"display_name": "Сергей Стамболцян", "username": "Sergstam", "kpi": "Выручка общая"},
    {"display_name": "Виктория Михно", "username": "vikamikhno", "kpi": "Выручка SVOD"},
    {"display_name": "Ренат Шаяхметов", "username": "Chess2707", "kpi": "DAU core"},
    {"display_name": "Данила Овчаров", "username": "DO009", "kpi": "DAU эмбед"},
    {"display_name": "Надежда Петрушенко", "username": "nadezhda_hr", "kpi": "ФОТ"},
    {"display_name": "Екатерина Бокова", "username": "katerina_bokova", "kpi": "Выручка AVOD"},
    {"display_name": "Сергей Иванов", "username": "s5069561", "kpi": "Выручка New bus"},
    {"display_name": "Дмитрий Егоров", "username": "Dmitry_Egorov", "kpi": "Оптимизация IT"},
    {"display_name": "Егор Великогло", "username": "egorv", "kpi": "Watchtime UGC контента"},
    {"display_name": "Лилия Мансурская", "username": "Lily_mans", "kpi": "FOCF"},
    {"display_name": "Евгений Ильчук", "username": "Evilchuk", "kpi": "Retention"},
    {"display_name": "Дарья Ю", "username": None, "kpi": "NPS"},
    {"display_name": "Мария С", "username": "divo_divnoe_by_masha", "kpi": "Watchtime проф. контента"},
]
