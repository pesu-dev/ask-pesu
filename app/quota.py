"""LLM Quota Management using a State Machine."""

import datetime
import logging
from dataclasses import dataclass

import pytz

IST = pytz.timezone("Asia/Kolkata")


@dataclass
class QuotaState:
    """Manages LLM quota state with cooldown logic."""

    name: str
    enabled: bool = True
    disabled_until: datetime.datetime | None = None
    cooldown_hours: int = 24

    def refresh(self) -> None:
        """Re-enable if cooldown has expired."""
        now = datetime.datetime.now(IST)
        if not self.enabled and self.disabled_until and now >= self.disabled_until:
            self.enabled, self.disabled_until = True, None
            logging.info(f"{self.name} cooldown expired, re-enabled for use.")

    def disable(self) -> None:
        """Disable for cooldown period."""
        now = datetime.datetime.now(IST)
        self.enabled = False
        self.disabled_until = now + datetime.timedelta(hours=self.cooldown_hours)
        logging.warning(f"Quota exceeded on llm:{self.name}. Disabled until {self.disabled_until}")

    def status(self) -> dict:
        """Get current status."""
        return {
            "available": self.enabled,
            "next_available": self.disabled_until.isoformat()
            if not self.enabled and self.disabled_until
            else None,
        }
