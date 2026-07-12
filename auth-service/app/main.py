from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import engine, redis_client
from app.routers import router


@asynccontextmanager
async def lifespan(app: FastAPI):
 
    yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(
    title="Auth Service",
    description="Authentication microservice: registration, JWT login, "
    "refresh rotation, logout, and role-based access control.",
    lifespan=lifespan,
)

app.include_router(router)
