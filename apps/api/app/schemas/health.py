"""Response models for the health endpoints."""

from typing import Literal

from pydantic import BaseModel


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"


class ReadinessChecks(BaseModel):
    database: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ready"] = "ready"
    checks: ReadinessChecks
