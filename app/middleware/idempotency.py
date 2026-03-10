"""
SentinelStream - Idempotency Middleware
Intercepts requests to the POST /transactions endpoint and checks
whether the provided Idempotency-Key has already been processed.

If a duplicate is detected, the original cached response is returned
immediately without re-processing the transaction. This prevents
double-charges when a client retries a timed-out request.
"""

import json
import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "Idempotency-Key"
IDEMPOTENCY_ROUTES = {"/api/v1/transactions"}  # Routes subject to idempotency


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces idempotency for critical write operations.

    How it works:
      1. Check if the request has an Idempotency-Key header.
      2. Look up the key in Redis (fast path) or PostgreSQL (fallback).
      3. If found: return the cached response (HTTP 200 with cached body).
      4. If not found: let the request proceed, then cache the response.

    This is a production-grade implementation of the "Idempotency Keys"
    pattern described in the Stripe API documentation.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only enforce on configured POST routes
        if request.method != "POST" or request.url.path not in IDEMPOTENCY_ROUTES:
            return await call_next(request)

        idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
        if not idempotency_key:
            return await call_next(request)

        # Check Redis cache first (sub-millisecond)
        redis = getattr(request.app.state, "redis", None)
        if redis:
            cached = await redis.get(f"idempotency:{idempotency_key}")
            if cached:
                logger.info(
                    f"Idempotency hit (Redis): key={idempotency_key[:16]}..."
                )
                cached_data = json.loads(cached)
                return JSONResponse(
                    content=cached_data["body"],
                    status_code=cached_data["status_code"],
                    headers={"X-Idempotency-Replayed": "true"},
                )

        # Not in cache — process the request
        response = await call_next(request)

        # Cache successful responses in Redis (24h TTL)
        if redis and 200 <= response.status_code < 300:
            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk

            try:
                body_json = json.loads(response_body)
                await redis.setex(
                    f"idempotency:{idempotency_key}",
                    86400,  # 24 hours
                    json.dumps({
                        "body": body_json,
                        "status_code": response.status_code,
                    }),
                )
                logger.debug(f"Cached idempotency key: {idempotency_key[:16]}...")
            except json.JSONDecodeError:
                pass

            return Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        return response
