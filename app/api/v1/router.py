"""SentinelStream - API v1 Router"""
from fastapi import APIRouter

from app.api.v1.endpoints import auth, transactions, admin

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(transactions.router)
api_router.include_router(admin.router)
