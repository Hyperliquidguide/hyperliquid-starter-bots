"""Risk limits every bot runs through before it sends an order.

These are a floor, not a strategy. Tighten them before you raise size.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    max_order_usd: float = 50.0  # largest single order, notional
    max_position_usd: float = 200.0  # largest absolute position, notional
    max_daily_loss_usd: float = 25.0  # equity drop from start that stops the bot


@dataclass
class RiskGuard:
    limits: RiskLimits
    start_equity: float | None = None
    halted: bool = False
    reasons: list[str] = field(default_factory=list)

    def set_start_equity(self, equity: float) -> None:
        self.start_equity = equity
        log.info("Risk guard armed: start equity $%.2f, daily loss limit $%.2f", equity, self.limits.max_daily_loss_usd)

    def check_equity(self, equity: float) -> bool:
        """Returns False (and halts) once the loss limit is hit."""
        if self.start_equity is None:
            self.set_start_equity(equity)
            return True
        loss = self.start_equity - equity
        if loss >= self.limits.max_daily_loss_usd:
            self._halt(f"loss ${loss:.2f} reached the ${self.limits.max_daily_loss_usd:.2f} limit")
            return False
        return not self.halted

    def allow_order(self, is_buy: bool, notional_usd: float, position_usd: float) -> bool:
        """position_usd is signed: positive long, negative short."""
        if self.halted:
            return False
        if notional_usd > self.limits.max_order_usd + 1e-9:
            log.warning("Blocked order: $%.2f is over max_order_usd $%.2f", notional_usd, self.limits.max_order_usd)
            return False
        after = position_usd + (notional_usd if is_buy else -notional_usd)
        # Orders that shrink the position are always allowed.
        if abs(after) > self.limits.max_position_usd + 1e-9 and abs(after) > abs(position_usd):
            log.info("Skipped %s: position would be $%.2f (limit $%.2f)", "buy" if is_buy else "sell", after, self.limits.max_position_usd)
            return False
        return True

    def _halt(self, reason: str) -> None:
        if not self.halted:
            log.error("HALT: %s", reason)
        self.halted = True
        self.reasons.append(reason)
