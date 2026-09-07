"""Per-model cooldown tracking for the inference provider's rate limits.

When a provider refuses a request on quota, retrying immediately just produces
more failures. Each model gets its own :class:`QuotaState`, so exhausting the
thinking model does not take normal mode down with it.

The state machine has two states and no timer. A model is disabled with a
deadline, and re-enabled lazily the next time it is looked at -- which avoids a
background task purely to flip a boolean.

This lives in process memory: it resets on restart, and separate replicas would
each track their own view.
"""

import datetime
import logging
from dataclasses import dataclass

import pytz

IST = pytz.timezone("Asia/Kolkata")


class QuotaExceededError(Exception):
    """Raised when a request asks for a model that is currently in cooldown.

    Signalled and handled entirely within this service: ``/ask`` raises it and an
    exception handler turns it into a 429. It is never raised by a library.
    """


@dataclass
class QuotaState:
    """Availability of one model, with an expiring cooldown.

    Attributes:
        name: Which model this tracks; appears in logs and in /quota.
        enabled: Whether the model may currently be used.
        disabled_until: When the cooldown lapses. None while enabled.
        cooldown_hours: How long :meth:`disable` blocks the model for. Defaults
            to 24, matching a daily provider quota window.
    """

    name: str
    enabled: bool = True
    disabled_until: datetime.datetime | None = None
    cooldown_hours: int = 24

    def refresh(self) -> None:
        """Re-enable the model if its cooldown has passed.

        Called before every read of :attr:`enabled`. Doing the expiry check on
        access rather than on a timer means there is no background task to run,
        and no window where the state is stale while something is looking at it.
        """
        now = datetime.datetime.now(IST)
        if not self.enabled and self.disabled_until and now >= self.disabled_until:
            self.enabled, self.disabled_until = True, None
            logging.info(f"{self.name} cooldown expired, re-enabled for use.")

    def disable(self) -> None:
        """Start a cooldown after the provider refused a request.

        Passed as the ``on_quota_exceeded`` callback into the RAG pipeline, which
        is the only way this can fire: a quota failure happens *during* streaming,
        long after the route handler has returned.
        """
        now = datetime.datetime.now(IST)
        self.enabled = False
        self.disabled_until = now + datetime.timedelta(hours=self.cooldown_hours)
        logging.warning(f"Quota exceeded on llm:{self.name}. Disabled until {self.disabled_until}")

    def status(self) -> dict:
        """Render this state for the /quota response.

        ``next_available`` is omitted while the model is usable, so clients can
        treat its presence as "currently blocked, retry after this".
        """
        return {
            "available": self.enabled,
            "next_available": self.disabled_until if not self.enabled and self.disabled_until else None,
        }
