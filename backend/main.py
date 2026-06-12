import logging
import os
import sys

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure the app directory is in the Python path for imports
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    load_dotenv()

# Log presence of critical API keys at startup (do not print full keys)
try:
    import logging as _logging
    _logger = _logging.getLogger(__name__)
    gemini_present = bool(os.environ.get("GEMINI_API_KEY", ""))
    groq_present = bool(os.environ.get("GROQ_API_KEY", ""))
    _logger.info("GEMINI_API_KEY present=%s, GROQ_API_KEY present=%s", gemini_present, groq_present)
    if gemini_present:
        _logger.info("GEMINI key prefix=%s", os.environ.get("GEMINI_API_KEY", "")[:10] + "...")
except Exception:
    pass

# Import API router
from routes import api

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Parallel AI",
    description="Autonomous Multimodal Agent Platform API",
    version="2.0.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routes
app.include_router(
    api.router,
    prefix="/api",
    tags=["API"]
)

# Root Endpoint
@app.get("/")
async def root():
    return {
        "message": "Parallel AI Backend Running",
        "version": "2.0.0",
        "status": "healthy"
    }

# Health Check Endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "Parallel AI Backend",
        "version": "2.0.0"
    }

# Startup Event
@app.on_event("startup")
async def startup_event():
    logger.info(" Parallel AI Backend Started")

# Shutdown Event
@app.on_event("shutdown")
async def shutdown_event():
    logger.info(" Parallel AI Backend Stopped")

# Run Server
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )