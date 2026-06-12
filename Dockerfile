# Stage 1: Build the frontend (Vite)
FROM node:18-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Setup Python backend
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies (ffmpeg is often needed for audio, though our STT is API based)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy backend requirements
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend from Stage 1 into the folder structure expected by main.py
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Expose port (Render/Cloud providers will inject PORT, defaulting to 8000)
ENV PORT=8000
EXPOSE 8000

# Start the FastAPI server
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
