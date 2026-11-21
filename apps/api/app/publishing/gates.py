"""Temporary authorization / configuration gate handling.

``next_attempt_at`` is reserved for genuine provider retry backoff.
Canary / missing-approval blocks must not park posts for days — the dispatcher
already filters them, and a short recheck is enough if a worker races a settings change.
"""

from __future__ import annotations

# Recheck soon if a worker observed a gate that the dispatcher normally excludes.
AUTH_GATE_RECHECK_SECONDS = 60
