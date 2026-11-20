"""Aggregates every version 1 router."""

from fastapi import APIRouter

from app.api.v1 import auth, connections, health

router = APIRouter()
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(connections.router)
