"""Estimated statutory charges for NSE cash-equity DELIVERY trades (simulation only).

These are ESTIMATES for paper P&L. Rates change; verify against your broker's
current charge sheet. Brokerage defaults to 0 for delivery.
"""
from __future__ import annotations

BROKERAGE_PER_ORDER = 0.0
STT_RATE = 0.001  # 0.1% on buy and sell (delivery)
EXCHANGE_TXN_RATE = 0.0000297  # NSE transaction charge
SEBI_RATE = 0.000001  # Rs 10 per crore
STAMP_DUTY_BUY_RATE = 0.00015  # 0.015% on buy
GST_RATE = 0.18
DP_CHARGE_SELL = 12.5  # per scrip per sell day, before GST


def estimate_charges(side: str, turnover: float) -> float:
    if turnover <= 0:
        return 0.0
    brokerage = BROKERAGE_PER_ORDER
    stt = turnover * STT_RATE
    exch = turnover * EXCHANGE_TXN_RATE
    sebi = turnover * SEBI_RATE
    stamp = turnover * STAMP_DUTY_BUY_RATE if side == "BUY" else 0.0
    dp = DP_CHARGE_SELL if side == "SELL" else 0.0
    gst = (brokerage + exch + sebi + dp) * GST_RATE
    return round(brokerage + stt + exch + sebi + stamp + dp + gst, 2)
