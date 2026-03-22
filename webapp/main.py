"""Web app — AI psychologist chat interface."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from app.ai_service import chat_response, transcribe_voice, text_to_speech
from config import ELEVENLABS_API_KEY

app = FastAPI(title="Aterley AI Psychologist")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory sessions
_sessions: dict[str, list[dict]] = {}


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    trigger_assessment: bool = False


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/v1", response_class=HTMLResponse)
async def variant1():
    return (STATIC_DIR / "v1.html").read_text(encoding="utf-8")


@app.get("/v2", response_class=HTMLResponse)
async def variant2():
    return (STATIC_DIR / "v2.html").read_text(encoding="utf-8")


@app.get("/v3", response_class=HTMLResponse)
async def variant3():
    return (STATIC_DIR / "v3.html").read_text(encoding="utf-8")


@app.post("/api/chat", response_model=ChatResponse)
async def api_chat(req: ChatRequest):
    sid = req.session_id or str(uuid.uuid4())
    if sid not in _sessions:
        _sessions[sid] = []

    history = _sessions[sid]
    reply = await chat_response(req.message, history)

    trigger = False
    if "[НАЧАТЬ_ОЦЕНКУ]" in reply:
        reply = reply.replace("[НАЧАТЬ_ОЦЕНКУ]", "").strip()
        trigger = True

    _sessions[sid].append({"role": "user", "content": req.message})
    _sessions[sid].append({"role": "assistant", "content": reply})

    # Keep last 20
    if len(_sessions[sid]) > 40:
        _sessions[sid] = _sessions[sid][-40:]

    return ChatResponse(reply=reply, session_id=sid, trigger_assessment=trigger)


@app.post("/api/transcribe")
async def api_transcribe(audio: UploadFile = File(...)):
    data = await audio.read()
    text = await transcribe_voice(data, filename=audio.filename or "voice.webm")
    return {"text": text}


@app.post("/api/tts")
async def api_tts(req: ChatRequest):
    audio_bytes = await text_to_speech(req.message)
    if not audio_bytes:
        return {"error": "TTS unavailable"}

    # ElevenLabs returns MP3, OpenAI returns opus
    media = "audio/mpeg" if ELEVENLABS_API_KEY else "audio/ogg"
    ext = "mp3" if ELEVENLABS_API_KEY else "ogg"

    return StreamingResponse(
        iter([audio_bytes]),
        media_type=media,
        headers={"Content-Disposition": f"inline; filename=response.{ext}"},
    )


class AssessmentResult(BaseModel):
    session_id: str
    scores: dict[str, int]


@app.post("/api/assessment_done")
async def api_assessment_done(req: AssessmentResult):
    """Save assessment results into chat history so AI knows about them."""
    sid = req.session_id
    if sid not in _sessions:
        _sessions[sid] = []

    labels = {
        "family_origin": "Родительская семья",
        "family_own": "Собственная семья",
        "life_fullness": "Полнота жизни",
        "realization": "Реализация",
        "integration": "Интеграция",
    }

    vals = list(req.scores.values())
    avg = sum(vals) / len(vals) if vals else 0

    summary_lines = []
    for key, label in labels.items():
        v = req.scores.get(key, 0)
        summary_lines.append(f"  {label}: {v}/10")

    summary = "\n".join(summary_lines)

    # Insert into history as system-like context
    _sessions[sid].append({
        "role": "user",
        "content": f"Я прошёл оценку ресурсного состояния. Вот мои результаты:\n{summary}\nСреднее: {avg:.1f}/10"
    })

    # Get AI response to the results
    reply = await chat_response(
        f"Я прошёл оценку ресурсного состояния. Вот мои результаты:\n{summary}\nСреднее: {avg:.1f}/10",
        _sessions[sid][:-1],  # history without the last message
    )

    _sessions[sid].append({"role": "assistant", "content": reply})

    return {"reply": reply, "average": round(avg, 1)}


class NeedsResult(BaseModel):
    session_id: str
    scores: dict[str, int]  # mental, social, emotional, spiritual, physical


@app.post("/api/needs_done")
async def api_needs_done(req: NeedsResult):
    """Save needs assessment results into chat history."""
    sid = req.session_id
    if sid not in _sessions:
        _sessions[sid] = []

    labels = {
        "mental": "Ментальная",
        "social": "Социальная",
        "emotional": "Эмоциональная",
        "spiritual": "Духовная",
        "physical": "Физическая",
    }

    vals = list(req.scores.values())
    avg = sum(vals) / len(vals) if vals else 0

    summary_lines = []
    for key, label in labels.items():
        v = req.scores.get(key, 0)
        summary_lines.append(f"  {label}: {v}/10")

    summary = "\n".join(summary_lines)

    _sessions[sid].append({
        "role": "user",
        "content": f"Я прошёл оценку потребностной сферы (обратная логика: 1=закрыта, 10=остро нужно).\n{summary}\nСреднее: {avg:.1f}/10"
    })

    reply = await chat_response(
        f"Я прошёл оценку потребностной сферы.\n{summary}\nСреднее: {avg:.1f}/10",
        _sessions[sid][:-1],
    )

    _sessions[sid].append({"role": "assistant", "content": reply})
    return {"reply": reply, "average": round(avg, 1)}


class FullAssessmentResult(BaseModel):
    session_id: str
    motivation_avg: float
    resource_scores: dict[str, int]
    needs_scores: dict[str, int]


@app.post("/api/full_assessment_done")
async def api_full_assessment_done(req: FullAssessmentResult):
    """Calculate derived metrics and return comprehensive results."""
    sid = req.session_id
    if sid not in _sessions:
        _sessions[sid] = []

    r_vals = list(req.resource_scores.values())
    n_vals = list(req.needs_scores.values())
    resource_avg = sum(r_vals) / len(r_vals) if r_vals else 0
    needs_avg = sum(n_vals) / len(n_vals) if n_vals else 0
    motivation_avg = req.motivation_avg

    # Derived calculations
    life_energy = resource_avg * needs_avg
    action_potential = (resource_avg * needs_avg * motivation_avg) / 10
    scu = (resource_avg + needs_avg + motivation_avg) / 3

    # Life energy interpretation
    if life_energy <= 30:
        le_text = "Не может быть социальным донором. Лидерство даётся непросто."
    elif life_energy <= 64:
        le_text = "Достаточный уровень для социального лидерства."
    else:
        le_text = "Избыточный уровень! Человек-аккумулятор."

    # Action potential interpretation
    if action_potential <= 17:
        ap_text = "Сохранение привычных границ области комфорта."
    elif action_potential <= 51:
        ap_text = "Расширение области комфорта путём выхода за её границы."
    else:
        ap_text = "Диффузное расширение изнутри."

    # SCU level
    scu_levels = [
        (1.0, 1.7, "Нулевой"),
        (1.8, 3.4, "Зависимый"),
        (3.5, 5.1, "Конформный"),
        (5.2, 6.8, "Достижительный"),
        (6.9, 8.4, "Постконвенциональный"),
        (8.5, 10.0, "Интегральный"),
    ]
    scu_name = "—"
    for low, high, name in scu_levels:
        if low <= scu <= high:
            scu_name = name
            break

    summary = (
        f"Комплексная оценка:\n"
        f"  Мотивация: {motivation_avg:.1f}/10\n"
        f"  Ресурс: {resource_avg:.1f}/10\n"
        f"  Потребности: {needs_avg:.1f}/10\n\n"
        f"  Жизненная энергия: {life_energy:.1f}% — {le_text}\n"
        f"  Потенциал действия: {action_potential:.1f}% — {ap_text}\n"
        f"  Социокультурный уровень: {scu:.1f}/10 — {scu_name}\n"
    )

    _sessions[sid].append({
        "role": "user",
        "content": f"Вот результаты моей комплексной оценки:\n{summary}"
    })

    reply = await chat_response(
        f"Вот результаты моей комплексной оценки:\n{summary}",
        _sessions[sid][:-1],
    )

    _sessions[sid].append({"role": "assistant", "content": reply})

    return {
        "reply": reply,
        "motivation_avg": round(motivation_avg, 1),
        "resource_avg": round(resource_avg, 1),
        "needs_avg": round(needs_avg, 1),
        "life_energy": round(life_energy, 1),
        "action_potential": round(action_potential, 1),
        "sociocultural_level": round(scu, 1),
        "scu_name": scu_name,
        "le_text": le_text,
        "ap_text": ap_text,
    }


@app.get("/api/session")
async def new_session():
    sid = str(uuid.uuid4())
    _sessions[sid] = []
    return {"session_id": sid}


@app.get("/api/debug")
async def debug_check():
    """Diagnostic endpoint — direct API call test."""
    import anthropic
    from config import CLAUDE_API_KEY, OPENAI_API_KEY, ELEVENLABS_API_KEY
    results = {}
    results["CLAUDE_API_KEY_len"] = len(CLAUDE_API_KEY) if CLAUDE_API_KEY else 0
    results["CLAUDE_API_KEY_start"] = CLAUDE_API_KEY[:20] + "..." if CLAUDE_API_KEY else "NOT SET"
    results["OPENAI_API_KEY_len"] = len(OPENAI_API_KEY) if OPENAI_API_KEY else 0
    results["ELEVENLABS_API_KEY_len"] = len(ELEVENLABS_API_KEY) if ELEVENLABS_API_KEY else 0
    # Direct Claude API test
    try:
        client = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)
        resp = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say OK"}],
        )
        results["claude_direct"] = f"SUCCESS: {resp.content[0].text}"
    except Exception as e:
        import traceback
        results["claude_direct"] = f"FAILED: {type(e).__name__}: {e}"
        results["claude_traceback"] = traceback.format_exc()[-500:]
    return results
