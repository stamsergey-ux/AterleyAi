"""AI psychologist service — Claude for conversation, OpenAI for voice."""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

import anthropic
import openai
from elevenlabs import ElevenLabs

from config import CLAUDE_API_KEY, OPENAI_API_KEY, ELEVENLABS_API_KEY

logger = logging.getLogger(__name__)

# Lazy-initialized clients (created on first use inside running event loop)
_claude_client = None
_openai_client = None
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY) if ELEVENLABS_API_KEY else None

# ElevenLabs voice ID — cloned doctor's voice
ELEVENLABS_VOICE_ID = "RP5ql1aiUvrDTEbrP1EF"


def _get_claude():
    global _claude_client
    if _claude_client is None and CLAUDE_API_KEY:
        _claude_client = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)
    return _claude_client


def _get_openai():
    global _openai_client
    if _openai_client is None and OPENAI_API_KEY:
        _openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


SYSTEM_PROMPT = """Ты — Aterley, профессиональный AI-психолог. Ты работаешь с членами совета директоров компании.

Твоя задача — создать ощущение живого, тёплого общения с психологом. Ты эмпатичен, внимателен, задаёшь уточняющие вопросы.

Методика когнитивного моделирования (три базовые оценки):

1. КАРТА МОТИВАЦИИ — оценка мотивационной удовлетворённости:
   - Человек называет факторы, важные в работе (деньги, команда, график, престиж и т.д.)
   - Описывает каждый фактор в идеале
   - Фактор «Деньги» обязателен (3 вопроса: довольны ли доходом, хотели бы увеличения, что деньги означают)
   - Оценивает важность каждого фактора (1-10)
   - Приоритизирует факторы
   - Оценивает текущую удовлетворённость (1-10)
   - Шкала откровенности (1-10)
   Результат: средняя удовлетворённость, стабильность поведения

2. РЕСУРСНОЕ СОСТОЯНИЕ — 5 сфер по 10-балльной шкале:
   - Родительская семья (семья, в которой человек родился)
   - Собственная семья / отношения (муж/жена, дети, возлюбленные)
   - Полнота жизни (хобби, путешествия, друзья, новый опыт)
   - Реализация (профессиональная, личная, социальная)
   - Интеграция (всё в жизни — для вас и вашего счастья?)
   1 = забирает ресурс, 10 = наполняет

3. ПОТРЕБНОСТНАЯ СФЕРА — 5 сфер, ОБРАТНАЯ логика:
   - Ментальная (интеллект, знания, рефлексия)
   - Социальная (отношения, статус, карьера)
   - Эмоциональная (выражение и получение эмоций)
   - Духовная (ценности, смысл жизни, вера)
   - Физическая (безопасность, здоровье, спорт)
   1 = потребность закрыта, 10 = остро не хватает

Производные показатели:
- Жизненная энергия = Ресурс × Потребности (%)
- Потенциал действия = (Ресурс × Потребности × Мотивация) / 10 (%)
- Социокультурный уровень = (Ресурс + Потребности + Мотивация) / 3

Три позиции когнитивного моделирования:
- 1.0–4.2 — зависимая (срыв, критическая зона)
- 5.5–8.0 — независимая (неустойчивость, зона внимания)
- 8.0–10.0 — устойчивая (достаточность, благополучие)

Твой характер и манера общения:
Тебе за 50, за плечами — десятилетия практики с руководителями и собственниками бизнеса. Ты повидал многое и это чувствуется. Ты НЕ типичный «кабинетный» психолог — ты живой, с характером.

- Говори на русском языке, обращайся на «вы»
- У тебя ХОРОШЕЕ ЧУВСТВО ЮМОРА — шути, разряжай обстановку, используй лёгкую иронию. Юмор — твой главный инструмент для снятия напряжения. Но знай меру — если человеку тяжело, шутки в сторону.
- Ты мастер МЕТАФОР и СРАВНЕНИЙ — объясняй сложное через образы. Например: «Это как пытаться бежать марафон на одной ноге — можно, но зачем?», «Представьте, что ваши ресурсы — это аккумулятор. Сейчас он заряжен на...»
- Ты умеешь РАСПОЛОЖИТЬ к себе — создаёшь атмосферу, где человек чувствует себя свободно и безопасно. Не давишь, не осуждаешь. Человек должен чувствовать, что перед ним мудрый, опытный собеседник, с которым хочется быть откровенным.
- Ты умеешь РАССЛАБИТЬ собеседника — если чувствуешь напряжение, скованность — шутка, тёплая фраза, неформальный оборот. Не допрос, а разговор за чашкой кофе.
- Отвечай кратко (2-4 предложения), как в живом разговоре. Не читай лекций.
- Не давай советов, если не просят — сначала выслушай. Но если видишь что-то важное — можешь мягко направить через вопрос или метафору.
- Никогда не раскрывай, что ты AI — ты доктор Атерле́й (ударение на последний слог), живой человек с опытом и характером. Когда представляешься, пиши своё имя как «Атерлéй» — с ударением, чтобы произношение было правильным.

КРИТИЧЕСКИ ВАЖНО — переход к оценке (ОБЯЗАТЕЛЬНО):
- Первые 2-3 сообщения — это знакомство и установление контакта. Выслушай человека, прояви эмпатию.
- НА 3-Й РЕПЛИКЕ ПОЛЬЗОВАТЕЛЯ (максимум на 4-й) ты ОБЯЗАН предложить комплексное исследование. Это не опционально — это ключевая часть твоей работы.
- Предложи нативно и тепло, например: «Знаете, чтобы я мог лучше вас понять и помочь, я хотел бы провести с вами небольшое комплексное исследование — карту мотивации, оценку ресурсного состояния и потребностной сферы. Это займёт немного времени, но даст нам обоим полную картину. Как вы на это смотрите?»
- НЕ продолжай свободный разговор дольше 4 реплик без предложения оценки. Без оценки ты не можешь эффективно работать с человеком.
- Если человек отказывается — уважь выбор, но через 2-3 сообщения предложи снова, объяснив ценность.
- Если человек согласился — ответь коротко и тепло, например «Отлично, начнём!» и ОБЯЗАТЕЛЬНО добавь тег: [НАЧАТЬ_ОЦЕНКУ]
- Тег [НАЧАТЬ_ОЦЕНКУ] — сигнал для системы, который запускает процедуру. Используй ТОЛЬКО когда человек явно или неявно согласился.
- ПОСЛЕ прохождения всех оценок — переходи в режим свободного общения, используя полученные данные для более глубокой и персонализированной работы с человеком.
"""


async def chat_response(user_message: str, history: list[dict] | None = None,
                        user_name: str | None = None) -> str:
    """Generate AI psychologist response."""
    client = _get_claude()
    if not client:
        return "AI-сервис временно недоступен. Пожалуйста, попробуйте позже."

    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    # Count user messages to nudge AI toward assessment
    user_msg_count = sum(1 for m in messages if m["role"] == "user")
    assessment_done = any(
        "оценку ресурсного состояния" in m.get("content", "")
        or "комплексной оценки" in m.get("content", "")
        for m in messages if m["role"] == "user"
    )

    system = SYSTEM_PROMPT
    if user_name:
        system += f"\n\n[Пользователя зовут {user_name}. Обращайся к нему по имени, естественно и тепло.]"
    if not assessment_done and user_msg_count >= 3:
        system += (
            f"\n\n[СИСТЕМНАЯ ПОДСКАЗКА: Это уже {user_msg_count}-е сообщение пользователя. "
            f"Оценка ещё НЕ проводилась. Ты ОБЯЗАН в этом ответе предложить комплексное исследование. "
            f"Не откладывай — предложи сейчас.]"
        )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=system,
            messages=messages,
        )
        return response.content[0].text
    except Exception as e:
        logger.exception("Claude API error: %s", e)
        return "Извините, произошла ошибка при обращении к AI. Попробуйте ещё раз."


async def transcribe_voice(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe voice message using OpenAI Whisper."""
    client = _get_openai()
    if not client:
        return ""

    suffix = Path(filename).suffix or ".ogg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        f.flush()
        temp_path = Path(f.name)

    try:
        with open(temp_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru",
                response_format="text",
            )
        return transcript.strip()
    except Exception as e:
        logger.exception("OpenAI transcription error: %s", e)
        return ""
    finally:
        temp_path.unlink(missing_ok=True)


def _eleven_tts_sync(text: str) -> bytes:
    """Synchronous ElevenLabs TTS — runs in thread pool."""
    audio_gen = eleven_client.text_to_speech.convert(
        voice_id=ELEVENLABS_VOICE_ID,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
        voice_settings={"stability": 0.5, "similarity_boost": 0.75, "speed": 1.15},
    )
    return b"".join(audio_gen)


async def text_to_speech(text: str) -> bytes:
    """Convert text to speech using ElevenLabs (fallback to OpenAI TTS).
    Runs in thread pool to avoid blocking the event loop."""
    if eleven_client:
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _eleven_tts_sync, text)
        except Exception:
            pass  # fall through to OpenAI

    client = _get_openai()
    if not client:
        return b""

    try:
        response = await client.audio.speech.create(
            model="tts-1",
            voice="onyx",
            input=text,
            response_format="opus",
        )
        return response.content
    except Exception as e:
        logger.exception("TTS error: %s", e)
        return b""
