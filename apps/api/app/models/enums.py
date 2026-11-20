"""Shared database enumerations."""

from enum import StrEnum


class ConnectionStatus(StrEnum):
    """Lifecycle of a stored LinkedIn authorization."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    REAUTH_REQUIRED = "reauth_required"
