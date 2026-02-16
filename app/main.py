import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.routes.images import router as images_router
from app.routes.screenshot import router as screenshot_router
from app.services.browser_pool import browser_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting browser pool...")
    await browser_pool.start()
    yield
    logger.info("Shutting down browser pool...")
    await browser_pool.stop()


app = FastAPI(lifespan=lifespan)

# Rate limiter
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "Too many requests. Please try again later."},
    )


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    first_error = exc.errors()[0] if exc.errors() else {}
    return JSONResponse(
        status_code=400,
        content={"error": first_error.get("msg", "Validation error")},
    )


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=86400,
)

# Routes
app.include_router(screenshot_router, prefix="/api")
app.include_router(images_router, prefix="/api")


@app.get("/")
async def health():
    return {"status": "ok", "service": "company-analyzer"}
