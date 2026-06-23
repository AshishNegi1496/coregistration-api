from contextlib import asynccontextmanager

from fastapi import FastAPI

from bootstrap import ensure_schema
from db import Base, engine
from folder_monitor_service import FolderMonitorService
from scheduler_service import SchedulerService
from routers import jobs, ui, scheduler
from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    monitor = FolderMonitorService(settings.target_root)
    monitor.start()
    app.state.folder_monitor = monitor
    scheduler_service = SchedulerService()
    scheduler_service.start()
    app.state.scheduler_service = scheduler_service
    try:
        yield
    finally:
        scheduler_service.stop()
        monitor.stop()


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
