"""Aggregates every version 1 router."""

from fastapi import APIRouter

from app.api.v1 import admin_ai, assistant, auth, connections, health, posts, publishing

router = APIRouter()
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(connections.router)
router.include_router(posts.router)
router.include_router(publishing.router)
router.include_router(assistant.router)
router.include_router(admin_ai.router)
