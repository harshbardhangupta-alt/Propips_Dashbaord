"""SQLAlchemy ORM models.

All datetimes are stored as naive UTC. Every paper-trading row carries
``simulated=True``; there is no model for real broker orders.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Instrument(Base):
    __tablename__ = "instruments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(200), default="")
    isin: Mapped[str | None] = mapped_column(String(16))
    industry: Mapped[str | None] = mapped_column(String(120))
    exchange_segment: Mapped[str] = mapped_column(String(16), default="NSE_EQ")
    security_id: Mapped[str | None] = mapped_column(String(20), index=True)
    series: Mapped[str | None] = mapped_column(String(8))
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size: Mapped[float] = mapped_column(Float, default=0.05)
    # MAPPED | MISSING_IN_SCRIP_MASTER | UNMAPPED
    mapping_status: Mapped[str] = mapped_column(String(32), default="UNMAPPED")
    mapping_note: Mapped[str | None] = mapped_column(Text)
    mapped_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class UniverseMember(Base):
    __tablename__ = "universe_members"
    __table_args__ = (UniqueConstraint("universe", "instrument_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    universe: Mapped[str] = mapped_column(String(16), index=True)  # NIFTY100 | NIFTY250
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)
    instrument: Mapped[Instrument] = relationship()


class UniverseRefresh(Base):
    __tablename__ = "universe_refreshes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    universe: Mapped[str] = mapped_column(String(32))  # NIFTY100 | NIFTY250 | SCRIP_MASTER
    source: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16))  # SUCCESS | FAILED | PARTIAL
    count: Mapped[int] = mapped_column(Integer, default=0)
    added: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Quote(Base):
    __tablename__ = "quotes"
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    ltp: Mapped[float | None] = mapped_column(Float)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    prev_close: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64), default="DHAN_REST_MARKETFEED_OHLC")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MTFSnapshot(Base):
    """Dashboard 1 multi-timeframe evaluation for one instrument."""

    __tablename__ = "mtf_snapshots"
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    daily_trend: Mapped[str] = mapped_column(String(16), default="UNAVAILABLE")
    h4_trend: Mapped[str] = mapped_column(String(16), default="UNAVAILABLE")
    m15_status: Mapped[str] = mapped_column(String(24), default="UNAVAILABLE")
    m5_status: Mapped[str] = mapped_column(String(24), default="UNAVAILABLE")
    bias: Mapped[str] = mapped_column(String(16), default="UNAVAILABLE")
    confirmation: Mapped[str] = mapped_column(String(16), default="UNAVAILABLE")
    quality: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ScanRun(Base):
    __tablename__ = "scan_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # SCHEDULED | MANUAL | AFTER_MARKET
    status: Mapped[str] = mapped_column(String(16), default="RUNNING")  # RUNNING|SUCCESS|PARTIAL|FAILED|CANCELLED
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    universe_size: Mapped[int] = mapped_column(Integer, default=0)
    scanned: Mapped[int] = mapped_column(Integer, default=0)
    qualified: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    unavailable: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(80))


class Signal(Base):
    """Dashboard 2 Mechanical Swing evaluation for one instrument."""

    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    scan_run_id: Mapped[int | None] = mapped_column(ForeignKey("scan_runs.id"))
    # QUALIFIED | REJECTED | UNAVAILABLE
    status: Mapped[str] = mapped_column(String(16), index=True)
    # Deterministic hash of (symbol, impulse high ts, confirmation candle ts) for qualified setups.
    signal_key: Mapped[str | None] = mapped_column(String(64), index=True)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_new: Mapped[bool] = mapped_column(Boolean, default=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    grade: Mapped[str] = mapped_column(String(8), default="-")
    ltp: Mapped[float | None] = mapped_column(Float)
    pct_change: Mapped[float | None] = mapped_column(Float)
    entry: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    target: Mapped[float | None] = mapped_column(Float)
    reward_risk: Mapped[float | None] = mapped_column(Float)
    suggested_qty: Mapped[int | None] = mapped_column(Integer)
    capital_required: Mapped[float | None] = mapped_column(Float)
    planned_risk: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    components: Mapped[dict] = mapped_column(JSON, default=dict)
    rejection_reasons: Mapped[list] = mapped_column(JSON, default=list)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    validity: Mapped[str] = mapped_column(String(16), default="VALID")  # VALID | EXPIRED | INVALIDATED | N/A
    invalidated_reason: Mapped[str | None] = mapped_column(Text)
    after_market: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    instrument: Mapped[Instrument] = relationship()


class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)  # D1_MTF | D2_MECH
    name: Mapped[str] = mapped_column(String(80))
    strategy: Mapped[str] = mapped_column(String(32))
    initial_capital: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)  # cash not invested in open positions (includes reserved)
    reserved: Mapped[float] = mapped_column(Float, default=0)  # earmarked for pending entries
    realized_gross: Mapped[float] = mapped_column(Float, default=0)
    total_charges: Mapped[float] = mapped_column(Float, default=0)
    total_slippage: Mapped[float] = mapped_column(Float, default=0)
    # Risk configuration (per account, so D1 and D2 are independent).
    risk_pct_per_trade: Mapped[float] = mapped_column(Float, default=1.0)
    max_risk_per_trade: Mapped[float] = mapped_column(Float, default=2000.0)
    max_allocation_per_trade: Mapped[float] = mapped_column(Float, default=50_000.0)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=5)
    max_aggregate_risk_pct: Mapped[float] = mapped_column(Float, default=5.0)
    min_reward_risk: Mapped[float] = mapped_column(Float, default=2.0)
    slippage_bps: Mapped[float] = mapped_column(Float, default=5.0)
    max_entry_deviation_pct: Mapped[float] = mapped_column(Float, default=0.5)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    reset_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PaperTrade(Base):
    """One simulated trade: configuration -> pending entry -> open position -> closed."""

    __tablename__ = "paper_trades"
    __table_args__ = (UniqueConstraint("account_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), index=True)
    strategy: Mapped[str] = mapped_column(String(32))  # DASHBOARD1_MTF | DASHBOARD2_MECHANICAL
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    signal_key: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    # CONFIGURED | PENDING_ENTRY | OPEN | CLOSED | CANCELLED | REJECTED | EXPIRED
    status: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(4), default="BUY")
    entry_trigger: Mapped[str] = mapped_column(String(32))
    planned_entry: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    allocation: Mapped[float] = mapped_column(Float)
    max_risk_amount: Mapped[float | None] = mapped_column(Float)
    planned_qty: Mapped[int] = mapped_column(Integer)
    planned_risk: Mapped[float] = mapped_column(Float)
    planned_reward: Mapped[float] = mapped_column(Float)
    reward_risk: Mapped[float] = mapped_column(Float)
    reserved_amount: Mapped[float] = mapped_column(Float, default=0)
    auto_entry_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    original_values: Mapped[dict | None] = mapped_column(JSON)
    filled_qty: Mapped[int] = mapped_column(Integer, default=0)
    entry_price: Mapped[float | None] = mapped_column(Float)
    entry_reference_price: Mapped[float | None] = mapped_column(Float)
    entry_at: Mapped[datetime | None] = mapped_column(DateTime)
    exit_price: Mapped[float | None] = mapped_column(Float)
    exit_reference_price: Mapped[float | None] = mapped_column(Float)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime)
    exit_reason: Mapped[str | None] = mapped_column(String(32))
    gross_pnl: Mapped[float | None] = mapped_column(Float)
    charges: Mapped[float] = mapped_column(Float, default=0)
    slippage_cost: Mapped[float] = mapped_column(Float, default=0)
    net_pnl: Mapped[float | None] = mapped_column(Float)
    last_price: Mapped[float | None] = mapped_column(Float)
    last_price_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_candle_ts: Mapped[float | None] = mapped_column(Float)  # epoch of last processed 5m candle
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # MTF / signal context at configuration
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    account: Mapped[PaperAccount] = relationship()
    events: Mapped[list["TradeEvent"]] = relationship(back_populates="trade", order_by="TradeEvent.id")
    executions: Mapped[list["Execution"]] = relationship(back_populates="trade", order_by="Execution.id")


class Execution(Base):
    """A simulated fill. (trade_id, side) is unique: each trade fills once in, once out."""

    __tablename__ = "executions"
    __table_args__ = (UniqueConstraint("trade_id", "side"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("paper_trades.id"), index=True)
    side: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    reference_price: Mapped[float] = mapped_column(Float)
    slippage: Mapped[float] = mapped_column(Float)
    charges: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(32))
    candle_ts: Mapped[float | None] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    trade: Mapped[PaperTrade] = relationship(back_populates="executions")


class TradeEvent(Base):
    __tablename__ = "trade_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("paper_trades.id"), index=True)
    event: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    trade: Mapped[PaperTrade] = relationship(back_populates="events")


class JobStatus(Base):
    __tablename__ = "job_status"
    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_status: Mapped[str | None] = mapped_column(String(24))
    last_message: Mapped[str | None] = mapped_column(Text)
    run_count: Mapped[int] = mapped_column(Integer, default=0)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(8))  # INFO | WARN | ERROR
    source: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
