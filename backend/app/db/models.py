from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class FlowRecord(Base):
    """One Keitaro flow the editor has fetched: base + pending ops (plan decision 2)."""

    __tablename__ = "flows"

    stream_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    position: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(String, default="")
    base: Mapped[dict[str, Any]] = mapped_column(JSON)
    pending: Mapped[list[Any]] = mapped_column(JSON)
    kt_signature: Mapped[list[Any]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)


class CreatedCampaign(Base):
    """Campaigns this app created, keyed by the client's idempotency key."""

    __tablename__ = "created_campaigns"

    idempotency_key: Mapped[str] = mapped_column(String, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
