import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import engine, redis_client
from app.routers import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tables are NOT created here — see DATABASE_SETUP.md / schema.sql
    yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(
    title="Product Service",
    description="Product catalog microservice: Redis-cached reads, inventory "
    "management, and role-based rules via JWTs issued by the Auth Service.",
    lifespan=lifespan,
)

app.include_router(router)


