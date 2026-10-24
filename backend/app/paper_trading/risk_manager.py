"""Position sizing and trade-plan validation (BUY only). Pure functions.

Per-share risk = Entry - Stop
Risk budget    = min(Available cash x risk%, configured max risk per trade, user max risk)
Quantity       = min(floor(Allocation / Entry), floor(Risk budget / Per-share risk)),
                 rounded down to the instrument lot size (1 for NSE cash equity).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.paper_trading.charges import estimate_charges


@dataclass
class AccountLimits:
    available_cash: float
    initial_capital: float
    risk_pct_per_trade: float
    max_risk_per_trade: float
    max_allocation_per_trade: float
    max_open_positions: int
    max_aggregate_risk_pct: float
    min_reward_risk: float
    open_or_pending_count: int = 0
    aggregate_open_risk: float = 0.0


@dataclass
class PlanInput:
    entry: float
    stop: float
    target: float
    allocation: float
    max_risk_amount: float | None = None
    lot_size: int = 1


@dataclass
class PlanResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quantity: int = 0
    per_share_risk: float = 0.0
    risk_budget: float = 0.0
    planned_risk: float = 0.0
    potential_reward: float = 0.0
    reward_risk: float = 0.0
    capital_required: float = 0.0
    estimated_buy_charges: float = 0.0
    remaining_cash: float = 0.0
    limiting_factor: str = ""

    def to_dict(self) -> dict:
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def _finite_pos(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def validate_plan(p: PlanInput, lim: AccountLimits) -> PlanResult:
    r = PlanResult(ok=False)
    for name, v in (("Entry price", p.entry), ("Stop loss", p.stop), ("Take profit", p.target), ("Fund allocation", p.allocation)):
        if not _finite_pos(v):
            r.errors.append(f"{name} must be a positive number")
    if p.max_risk_amount is not None and not _finite_pos(p.max_risk_amount):
        r.errors.append("Maximum monetary risk must be a positive number when provided")
    if r.errors:
        return r
    if not (p.entry > p.stop > 0):
        r.errors.append("For a BUY, Entry Price > Stop Loss > 0 is required")
    if not (p.target > p.entry):
        r.errors.append("For a BUY, Take Profit must be above the Entry Price")
    if p.allocation > lim.available_cash + 1e-9:
        r.errors.append(f"Allocation Rs {p.allocation:,.2f} exceeds available paper cash Rs {lim.available_cash:,.2f}")
    if p.allocation > lim.max_allocation_per_trade + 1e-9:
        r.errors.append(f"Allocation exceeds the maximum per-trade allocation Rs {lim.max_allocation_per_trade:,.2f}")
    if lim.open_or_pending_count >= lim.max_open_positions:
        r.errors.append(f"Maximum simultaneous positions/pending entries ({lim.max_open_positions}) reached")
    if r.errors and not (p.entry > p.stop and p.target > p.entry):
        return r

    r.per_share_risk = p.entry - p.stop
    reward = p.target - p.entry
    r.reward_risk = round(reward / r.per_share_risk, 2) if r.per_share_risk > 0 else 0.0
    if r.reward_risk < lim.min_reward_risk:
        r.errors.append(f"Reward:risk 1:{r.reward_risk} is below the mandatory minimum 1:{lim.min_reward_risk:g}")
    elif r.reward_risk < lim.min_reward_risk * 1.1:
        r.warnings.append(f"Reward:risk 1:{r.reward_risk} is close to the minimum 1:{lim.min_reward_risk:g}")

    budgets = {"risk % of available cash": lim.available_cash * lim.risk_pct_per_trade / 100.0, "max risk per trade": lim.max_risk_per_trade}
    if p.max_risk_amount is not None:
        budgets["your max monetary risk"] = p.max_risk_amount
    r.risk_budget = min(budgets.values())
    lot = max(1, int(p.lot_size))
    q_alloc = int(p.allocation // p.entry)
    q_risk = int(r.risk_budget // r.per_share_risk) if r.per_share_risk > 0 else 0
    q = min(q_alloc, q_risk)
    q -= q % lot
    r.limiting_factor = "allocation" if q_alloc <= q_risk else min(budgets, key=budgets.get)
    r.quantity = max(0, q)
    r.planned_risk = r.quantity * r.per_share_risk
    r.potential_reward = r.quantity * reward
    r.capital_required = r.quantity * p.entry
    r.estimated_buy_charges = estimate_charges("BUY", r.capital_required)
    r.remaining_cash = lim.available_cash - p.allocation
    if r.quantity < 1:
        r.errors.append(
            f"Calculated quantity is 0 (allocation allows {q_alloc}, risk budget Rs {r.risk_budget:,.2f} allows {q_risk}); increase allocation or tighten the plan"
        )
    agg_cap = lim.initial_capital * lim.max_aggregate_risk_pct / 100.0
    if r.quantity >= 1 and lim.aggregate_open_risk + r.planned_risk > agg_cap + 1e-9:
        r.errors.append(
            f"Aggregate planned risk Rs {lim.aggregate_open_risk + r.planned_risk:,.2f} would exceed the cap Rs {agg_cap:,.2f} ({lim.max_aggregate_risk_pct:g}% of capital)"
        )
    if r.capital_required + r.estimated_buy_charges > p.allocation and r.quantity >= 1:
        r.warnings.append("Estimated charges may reduce the filled quantity by 1 share to stay within the allocation")
    r.ok = not r.errors
    return r
