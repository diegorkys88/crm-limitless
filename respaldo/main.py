from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from database import Base
from db_session import engine
import os
from dotenv import load_dotenv

from routers import contacts, outreach, appointments, users, sync, webhooks, auth

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    print("✅ Database ready")
    yield
    print("👋 Shutting down")

app = FastAPI(
    title="AI-Powered CRM",
    description="CRM with Claude AI agents for automotive leadership coaching",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(auth.router,         prefix="/auth",         tags=["Auth"])
app.include_router(contacts.router,     prefix="/contacts",     tags=["Contacts"])
app.include_router(outreach.router,     prefix="/outreach",     tags=["Outreach"])
app.include_router(appointments.router, prefix="/appointments", tags=["Appointments"])
app.include_router(users.router,        prefix="/users",        tags=["Users"])
app.include_router(sync.router,         prefix="/sync",         tags=["Sync"])
app.include_router(webhooks.router,     prefix="/webhooks",     tags=["Webhooks"])

# ── Dashboard route BEFORE static mount ───────────────────────────────────────
@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse("static/index.html")

@app.get("/", include_in_schema=False)
def root():
    return FileResponse("static/index.html")

# ── Static files LAST ─────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")
