import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from app.database import init_db
from app.handlers import onboarding, motivation, assessment, needs, full_assessment, heatmap, notes, kpi, admin, chat

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    await init_db()
    logger.info("Database initialized")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Register routers (order matters — motivation/needs before chat catch-all)
    dp.include_router(onboarding.router)
    dp.include_router(full_assessment.router)
    dp.include_router(motivation.router)
    dp.include_router(assessment.router)
    dp.include_router(needs.router)
    dp.include_router(heatmap.router)
    dp.include_router(notes.router)
    dp.include_router(kpi.router)
    dp.include_router(admin.router)
    dp.include_router(chat.router)  # must be last — catches all remaining text/voice

    logger.info("Aterley AI Psychologist bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
