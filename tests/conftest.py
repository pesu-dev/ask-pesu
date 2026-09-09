"""Put ``services/api`` on the path so the ranking functions can be imported.

These tests live at the repository root rather than inside the service because
a ``git subtree split`` ships only ``services/<name>/`` to a Space, and there is
no reason for test code to travel to production.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "api"))
