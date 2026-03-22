"""Web app — AI psychologist chat interface."""
from __future__ import annotations

import hashlib
import uuid
import datetime as dt
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Request, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func, desc

from app.ai_service import chat_response, transcribe_voice, text_to_speech
from app.database import (
    async_session, init_db,
    Member, Assessment, MotivationAssessment, MotivationFactor,
    NeedsAssessment, DerivedMetrics,
)
from config import ELEVENLABS_API_KEY, DASHBOARD_PASSWORD

app = FastAPI(title="Aterley AI Psychologist")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory sessions
_sessions: dict[str, list[dict]] = {}


class ChatRequest(BaseModel):
    session_id: str
    message: str
    member_id: Optional[int] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    trigger_assessment: bool = False


@app.on_event("startup")
async def on_startup():
    await init_db()


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


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")


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
    member_id: Optional[int] = None


@app.post("/api/assessment_done")
async def api_assessment_done(req: AssessmentResult):
    """Save assessment results into chat history and optionally to DB."""
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

    _sessions[sid].append({
        "role": "user",
        "content": f"Я прошёл оценку ресурсного состояния. Вот мои результаты:\n{summary}\nСреднее: {avg:.1f}/10"
    })

    reply = await chat_response(
        f"Я прошёл оценку ресурсного состояния. Вот мои результаты:\n{summary}\nСреднее: {avg:.1f}/10",
        _sessions[sid][:-1],
    )
    _sessions[sid].append({"role": "assistant", "content": reply})

    # Save to DB if member_id provided
    if req.member_id:
        async with async_session() as session:
            assessment = Assessment(
                member_id=req.member_id,
                family_origin=req.scores.get("family_origin"),
                family_own=req.scores.get("family_own"),
                life_fullness=req.scores.get("life_fullness"),
                realization=req.scores.get("realization"),
                integration=req.scores.get("integration"),
                average=round(avg, 2),
            )
            session.add(assessment)
            await session.commit()

    return {"reply": reply, "average": round(avg, 1)}


class NeedsResult(BaseModel):
    session_id: str
    scores: dict[str, int]
    member_id: Optional[int] = None


@app.post("/api/needs_done")
async def api_needs_done(req: NeedsResult):
    """Save needs assessment results into chat history and optionally to DB."""
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

    if req.member_id:
        async with async_session() as session:
            needs = NeedsAssessment(
                member_id=req.member_id,
                mental=req.scores.get("mental"),
                social=req.scores.get("social"),
                emotional=req.scores.get("emotional"),
                spiritual=req.scores.get("spiritual"),
                physical=req.scores.get("physical"),
                average=round(avg, 2),
            )
            session.add(needs)
            await session.commit()

    return {"reply": reply, "average": round(avg, 1)}


class FullAssessmentResult(BaseModel):
    session_id: str
    motivation_avg: float
    resource_scores: dict[str, int]
    needs_scores: dict[str, int]
    member_id: Optional[int] = None


@app.post("/api/full_assessment_done")
async def api_full_assessment_done(req: FullAssessmentResult):
    """Calculate derived metrics, save to DB, and return comprehensive results."""
    sid = req.session_id
    if sid not in _sessions:
        _sessions[sid] = []

    r_vals = list(req.resource_scores.values())
    n_vals = list(req.needs_scores.values())
    resource_avg = sum(r_vals) / len(r_vals) if r_vals else 0
    needs_avg = sum(n_vals) / len(n_vals) if n_vals else 0
    motivation_avg = req.motivation_avg

    life_energy = resource_avg * needs_avg
    action_potential = (resource_avg * needs_avg * motivation_avg) / 10
    scu = (resource_avg + needs_avg + motivation_avg) / 3

    if life_energy <= 30:
        le_text = "Не может быть социальным донором. Лидерство даётся непросто."
    elif life_energy <= 64:
        le_text = "Достаточный уровень для социального лидерства."
    else:
        le_text = "Избыточный уровень! Человек-аккумулятор."

    if action_potential <= 17:
        ap_text = "Сохранение привычных границ области комфорта."
    elif action_potential <= 51:
        ap_text = "Расширение области комфорта путём выхода за её границы."
    else:
        ap_text = "Диффузное расширение изнутри."

    scu_levels = [
        (1.0, 1.7, "Нулевой"), (1.8, 3.4, "Зависимый"),
        (3.5, 5.1, "Конформный"), (5.2, 6.8, "Достижительный"),
        (6.9, 8.4, "Постконвенциональный"), (8.5, 10.0, "Интегральный"),
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

    if req.member_id:
        async with async_session() as session:
            dm = DerivedMetrics(
                member_id=req.member_id,
                motivation_avg=round(motivation_avg, 2),
                resource_avg=round(resource_avg, 2),
                needs_avg=round(needs_avg, 2),
                life_energy=round(life_energy, 2),
                action_potential=round(action_potential, 2),
                sociocultural_level=round(scu, 2),
            )
            session.add(dm)
            await session.commit()

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


# ══════════════════════════════════════════════════════════════════════════
# WEB REGISTRATION
# ══════════════════════════════════════════════════════════════════════════


class WebRegisterRequest(BaseModel):
    name: str
    company: Optional[str] = None
    position: Optional[str] = None


@app.post("/api/web/register")
async def web_register(req: WebRegisterRequest):
    """Register a web user as a Member and return member_id + session_id."""
    async with async_session() as session:
        result = await session.execute(
            select(Member).where(Member.display_name == req.name)
        )
        member = result.scalar_one_or_none()

        if not member:
            member = Member(
                display_name=req.name,
                company=req.company,
                position=req.position,
            )
            session.add(member)
            await session.commit()
            await session.refresh(member)

    sid = str(uuid.uuid4())
    _sessions[sid] = []
    return {"member_id": member.id, "session_id": sid}


# ══════════════════════════════════════════════════════════════════════════
# DASHBOARD API
# ══════════════════════════════════════════════════════════════════════════


def _make_token(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


async def _verify_token(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization[len("Bearer "):]
    if token != _make_token(DASHBOARD_PASSWORD):
        raise HTTPException(status_code=401, detail="Invalid token")


class LoginRequest(BaseModel):
    password: str


@app.post("/api/dashboard/login")
async def dashboard_login(req: LoginRequest):
    if req.password != DASHBOARD_PASSWORD:
        raise HTTPException(status_code=401, detail="Wrong password")
    return {"token": _make_token(req.password), "ok": True}


@app.get("/api/dashboard/patients")
async def dashboard_patients(authorization: str | None = Header(default=None)):
    await _verify_token(authorization)

    async with async_session() as session:
        result = await session.execute(select(Member))
        members = result.scalars().all()

        patients = []
        for m in members:
            dm_result = await session.execute(
                select(DerivedMetrics)
                .where(DerivedMetrics.member_id == m.id)
                .order_by(desc(DerivedMetrics.date))
                .limit(1)
            )
            latest_dm = dm_result.scalar_one_or_none()

            count_result = await session.execute(
                select(func.count(Assessment.id)).where(Assessment.member_id == m.id)
            )
            assessment_count = count_result.scalar() or 0

            last_date_result = await session.execute(
                select(func.max(Assessment.date)).where(Assessment.member_id == m.id)
            )
            last_assessment_date = last_date_result.scalar()

            patients.append({
                "id": m.id,
                "display_name": m.display_name,
                "username": m.username,
                "company": m.company,
                "position": m.position,
                "motivation_avg": latest_dm.motivation_avg if latest_dm else None,
                "resource_avg": latest_dm.resource_avg if latest_dm else None,
                "needs_avg": latest_dm.needs_avg if latest_dm else None,
                "life_energy": latest_dm.life_energy if latest_dm else None,
                "action_potential": latest_dm.action_potential if latest_dm else None,
                "sociocultural_level": latest_dm.sociocultural_level if latest_dm else None,
                "last_assessment_date": last_assessment_date.isoformat() if last_assessment_date else None,
                "assessment_count": assessment_count,
            })

    return {"patients": patients}


@app.get("/api/dashboard/patients/{patient_id}")
async def dashboard_patient_detail(patient_id: int, authorization: str | None = Header(default=None)):
    await _verify_token(authorization)

    async with async_session() as session:
        result = await session.execute(select(Member).where(Member.id == patient_id))
        member = result.scalar_one_or_none()
        if not member:
            raise HTTPException(status_code=404, detail="Patient not found")

        assessments_result = await session.execute(
            select(Assessment).where(Assessment.member_id == patient_id).order_by(Assessment.date)
        )
        assessments = assessments_result.scalars().all()

        mot_result = await session.execute(
            select(MotivationAssessment).where(MotivationAssessment.member_id == patient_id).order_by(MotivationAssessment.date)
        )
        motivation_assessments = mot_result.scalars().all()

        needs_result = await session.execute(
            select(NeedsAssessment).where(NeedsAssessment.member_id == patient_id).order_by(NeedsAssessment.date)
        )
        needs_assessments = needs_result.scalars().all()

        dm_result = await session.execute(
            select(DerivedMetrics).where(DerivedMetrics.member_id == patient_id).order_by(DerivedMetrics.date)
        )
        derived_metrics = dm_result.scalars().all()

    return {
        "member": {
            "id": member.id, "display_name": member.display_name,
            "username": member.username, "company": member.company,
            "position": member.position, "department": member.department,
            "gender": member.gender, "age": member.age,
            "created_at": member.created_at.isoformat() if member.created_at else None,
        },
        "assessments": [
            {"id": a.id, "date": a.date.isoformat() if a.date else None,
             "family_origin": a.family_origin, "family_own": a.family_own,
             "life_fullness": a.life_fullness, "realization": a.realization,
             "integration": a.integration, "average": a.average}
            for a in assessments
        ],
        "motivation_assessments": [
            {"id": ma.id, "date": ma.date.isoformat() if ma.date else None,
             "overall_satisfaction": ma.overall_satisfaction,
             "openness": ma.openness, "behavior_stability": ma.behavior_stability,
             "factors": [{"name": f.name, "importance": f.importance,
                          "priority_rank": f.priority_rank, "satisfaction": f.satisfaction}
                         for f in (ma.factors or [])]}
            for ma in motivation_assessments
        ],
        "needs_assessments": [
            {"id": na.id, "date": na.date.isoformat() if na.date else None,
             "mental": na.mental, "social": na.social, "emotional": na.emotional,
             "spiritual": na.spiritual, "physical": na.physical, "average": na.average}
            for na in needs_assessments
        ],
        "derived_metrics": [
            {"id": dm.id, "date": dm.date.isoformat() if dm.date else None,
             "motivation_avg": dm.motivation_avg, "resource_avg": dm.resource_avg,
             "needs_avg": dm.needs_avg, "life_energy": dm.life_energy,
             "action_potential": dm.action_potential,
             "sociocultural_level": dm.sociocultural_level,
             "behavior_stability": dm.behavior_stability}
            for dm in derived_metrics
        ],
    }


@app.get("/api/dashboard/patients/{patient_id}/pdf", response_class=HTMLResponse)
async def dashboard_patient_pdf(patient_id: int):
    """Generate a printable HTML report for a patient."""
    async with async_session() as session:
        result = await session.execute(select(Member).where(Member.id == patient_id))
        member = result.scalar_one_or_none()
        if not member:
            raise HTTPException(status_code=404, detail="Patient not found")

        dm_result = await session.execute(
            select(DerivedMetrics).where(DerivedMetrics.member_id == patient_id)
            .order_by(desc(DerivedMetrics.date)).limit(1)
        )
        latest_dm = dm_result.scalar_one_or_none()

        a_result = await session.execute(
            select(Assessment).where(Assessment.member_id == patient_id)
            .order_by(desc(Assessment.date)).limit(1)
        )
        latest_a = a_result.scalar_one_or_none()

        n_result = await session.execute(
            select(NeedsAssessment).where(NeedsAssessment.member_id == patient_id)
            .order_by(desc(NeedsAssessment.date)).limit(1)
        )
        latest_n = n_result.scalar_one_or_none()

    dm_rows = ""
    if latest_dm:
        dm_rows = f"""
        <tr><td>Мотивация (средн.)</td><td>{latest_dm.motivation_avg or '—'}</td></tr>
        <tr><td>Ресурс (средн.)</td><td>{latest_dm.resource_avg or '—'}</td></tr>
        <tr><td>Потребности (средн.)</td><td>{latest_dm.needs_avg or '—'}</td></tr>
        <tr><td><strong>Жизненная энергия</strong></td><td><strong>{latest_dm.life_energy or '—'}%</strong></td></tr>
        <tr><td><strong>Потенциал действия</strong></td><td><strong>{latest_dm.action_potential or '—'}%</strong></td></tr>
        <tr><td><strong>Социокультурный уровень</strong></td><td><strong>{latest_dm.sociocultural_level or '—'}/10</strong></td></tr>
        """

    resource_rows = ""
    if latest_a:
        resource_rows = f"""
        <tr><td>Родительская семья</td><td>{latest_a.family_origin or '—'}</td></tr>
        <tr><td>Собственная семья</td><td>{latest_a.family_own or '—'}</td></tr>
        <tr><td>Полнота жизни</td><td>{latest_a.life_fullness or '—'}</td></tr>
        <tr><td>Реализация</td><td>{latest_a.realization or '—'}</td></tr>
        <tr><td>Интеграция</td><td>{latest_a.integration or '—'}</td></tr>
        <tr><td><strong>Среднее</strong></td><td><strong>{latest_a.average or '—'}</strong></td></tr>
        """

    needs_rows = ""
    if latest_n:
        needs_rows = f"""
        <tr><td>Ментальная</td><td>{latest_n.mental or '—'}</td></tr>
        <tr><td>Социальная</td><td>{latest_n.social or '—'}</td></tr>
        <tr><td>Эмоциональная</td><td>{latest_n.emotional or '—'}</td></tr>
        <tr><td>Духовная</td><td>{latest_n.spiritual or '—'}</td></tr>
        <tr><td>Физическая</td><td>{latest_n.physical or '—'}</td></tr>
        <tr><td><strong>Среднее</strong></td><td><strong>{latest_n.average or '—'}</strong></td></tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Отчёт — {member.display_name}</title>
<style>
  @media print {{ body {{ margin: 1cm; }} }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #333; }}
  h1 {{ color: #2c3e50; border-bottom: 2px solid #8b7355; padding-bottom: 10px; }}
  h2 {{ color: #8b7355; margin-top: 30px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 10px 0 20px; }}
  th, td {{ padding: 8px 12px; border: 1px solid #ddd; text-align: left; }}
  th {{ background: #f4f6f9; }}
  .meta {{ color: #666; font-size: 0.9em; }}
  .print-btn {{ background: #8b7355; color: #fff; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-size: 1em; }}
  .print-btn:hover {{ background: #725f46; }}
  @media print {{ .no-print {{ display: none; }} }}
</style>
</head>
<body>
<div class="no-print" style="text-align:right; margin-bottom:20px;">
  <button class="print-btn" onclick="window.print()">Печать / Сохранить PDF</button>
</div>
<h1>Психологический отчёт</h1>
<p><strong>{member.display_name}</strong></p>
<p class="meta">Компания: {member.company or '—'} | Должность: {member.position or '—'} | Дата: {dt.datetime.utcnow().strftime('%d.%m.%Y')}</p>

<h2>Производные метрики</h2>
<table>{dm_rows if dm_rows else '<tr><td>Нет данных</td></tr>'}</table>

<h2>Ресурсное состояние</h2>
<table>{resource_rows if resource_rows else '<tr><td>Нет данных</td></tr>'}</table>

<h2>Потребностная сфера</h2>
<table>{needs_rows if needs_rows else '<tr><td>Нет данных</td></tr>'}</table>

<p class="meta" style="margin-top:40px;">Сгенерировано системой Aterley AI Psychologist</p>
</body>
</html>"""
    return HTMLResponse(content=html)
