from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.bootstrap import ensure_schema
from api.db import Base, engine
from api.routers import jobs, ui, scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    yield


app = FastAPI(
    title="Geospatial Coregistration API",
    description="FastAPI backend for managing target/base image jobs and Postgres persistence.",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(jobs.router, prefix="/api")
app.include_router(ui.router)
app.include_router(scheduler.router, prefix="/api")


@app.get("/")
async def root():
    return {"status": "ok", "docs": "/docs", "api_prefix": "/api"}
