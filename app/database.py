from __future__ import annotations

import datetime as dt
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, ForeignKey, BigInteger,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from config import DATABASE_URL


class Base(DeclarativeBase):
    pass


# ── Models ──────────────────────────────────────────────────────────────────


class Member(Base):
    """Board member profile."""
    __tablename__ = "members"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=True)
    username = Column(String(64), nullable=True)
    display_name = Column(String(128), nullable=False)
    company = Column(String(128), nullable=True)
    department = Column(String(128), nullable=True)
    position = Column(String(128), nullable=True)
    gender = Column(String(16), nullable=True)
    age = Column(Integer, nullable=True)
    work_start_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    assessments = relationship("Assessment", back_populates="member", lazy="selectin")
    kpis = relationship("KPI", back_populates="member", lazy="selectin")
    notes = relationship("PsychologistNote", back_populates="member", lazy="selectin")
    motivation_assessments = relationship("MotivationAssessment", back_populates="member", lazy="selectin")
    needs_assessments = relationship("NeedsAssessment", back_populates="member", lazy="selectin")
    derived_metrics = relationship("DerivedMetrics", back_populates="member", lazy="selectin")


class Assessment(Base):
    """Resource state assessment — 5 spheres + average."""
    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    date = Column(DateTime, default=dt.datetime.utcnow)

    # 5 resource spheres (1-10 scale)
    family_origin = Column(Float, nullable=True)       # Родительская семья
    family_own = Column(Float, nullable=True)           # Собственная семья / отношения
    life_fullness = Column(Float, nullable=True)        # Полнота жизни
    realization = Column(Float, nullable=True)          # Реализация
    integration = Column(Float, nullable=True)          # Интеграция

    average = Column(Float, nullable=True)              # Среднее по 5 сферам

    member = relationship("Member", back_populates="assessments")


class KPI(Base):
    """Individual KPI metric for a board member."""
    __tablename__ = "kpis"

    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    metric_name = Column(String(256), nullable=False)
    value_start = Column(Float, nullable=True)          # Значение на начало года
    value_current = Column(Float, nullable=True)        # Текущее значение
    value_target = Column(Float, nullable=True)         # Целевое на конец года
    updated_at = Column(DateTime, default=dt.datetime.utcnow)

    member = relationship("Member", back_populates="kpis")


class PsychologistNote(Base):
    """Psychologist's diary notes about a member."""
    __tablename__ = "psychologist_notes"

    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    author_username = Column(String(64), nullable=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    member = relationship("Member", back_populates="notes")


# ── Motivation Map ─────────────────────────────────────────────────────────


class MotivationAssessment(Base):
    """Motivation map session — overall results."""
    __tablename__ = "motivation_assessments"

    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    date = Column(DateTime, default=dt.datetime.utcnow)

    overall_satisfaction = Column(Float, nullable=True)   # Средняя удовлетворённость
    openness = Column(Float, nullable=True)               # Шкала откровенности (1-10)
    behavior_stability = Column(Float, nullable=True)     # Стабильность поведения

    factors = relationship("MotivationFactor", back_populates="assessment", lazy="selectin",
                           cascade="all, delete-orphan")
    member = relationship("Member", back_populates="motivation_assessments")


class MotivationFactor(Base):
    """Individual motivation factor within an assessment."""
    __tablename__ = "motivation_factors"

    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("motivation_assessments.id"), nullable=False)

    name = Column(String(256), nullable=False)            # Название фактора
    description = Column(Text, nullable=True)             # Описание в идеальном мире
    importance = Column(Float, nullable=True)             # Важность (1-10)
    priority_rank = Column(Integer, nullable=True)        # Приоритет (1 = наивысший)
    satisfaction = Column(Float, nullable=True)           # Удовлетворённость (1-10)

    # Special money questions (only for "Деньги" factor)
    money_satisfied = Column(Text, nullable=True)         # Довольны ли доходом?
    money_increase = Column(Text, nullable=True)          # Хотели бы увеличения? На сколько?
    money_meaning = Column(Text, nullable=True)           # Что деньги значат?

    assessment = relationship("MotivationAssessment", back_populates="factors")


# ── Needs Sphere ───────────────────────────────────────────────────────────


class NeedsAssessment(Base):
    """Needs sphere assessment — 5 spheres, reverse logic."""
    __tablename__ = "needs_assessments"

    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    date = Column(DateTime, default=dt.datetime.utcnow)

    # 5 needs spheres (1=satisfied, 10=strongly needed) — REVERSE logic
    mental = Column(Float, nullable=True)        # Ментальная / интеллектуальная
    social = Column(Float, nullable=True)        # Социальная
    emotional = Column(Float, nullable=True)     # Эмоциональная
    spiritual = Column(Float, nullable=True)     # Духовная / ценностная
    physical = Column(Float, nullable=True)      # Физическая

    average = Column(Float, nullable=True)       # Среднее по 5 сферам

    member = relationship("Member", back_populates="needs_assessments")


# ── Derived Metrics ────────────────────────────────────────────────────────


class DerivedMetrics(Base):
    """Derived metrics calculated from all three assessments."""
    __tablename__ = "derived_metrics"

    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    date = Column(DateTime, default=dt.datetime.utcnow)

    # Source assessment IDs
    motivation_id = Column(Integer, ForeignKey("motivation_assessments.id"), nullable=True)
    resource_id = Column(Integer, ForeignKey("assessments.id"), nullable=True)
    needs_id = Column(Integer, ForeignKey("needs_assessments.id"), nullable=True)

    # Source averages (for convenience)
    motivation_avg = Column(Float, nullable=True)
    resource_avg = Column(Float, nullable=True)
    needs_avg = Column(Float, nullable=True)

    # Derived calculations
    life_energy = Column(Float, nullable=True)            # Ресурс × Потребности (%)
    action_potential = Column(Float, nullable=True)       # (Ресурс × Потребности × Мотивация) / 10 (%)
    sociocultural_level = Column(Float, nullable=True)    # (Ресурс + Потребности + Мотивация) / 3
    behavior_stability = Column(Float, nullable=True)     # Из карты мотивации

    member = relationship("Member", back_populates="derived_metrics")


# ── Engine & Session ────────────────────────────────────────────────────────

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
