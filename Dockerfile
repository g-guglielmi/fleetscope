# Single-image build: React SPA (built with Node) served by the FastAPI app.
# Result is one container that does both the UI and the API, backed by SQLite.

# --- Stage 1: build the frontend ---
FROM node:20-alpine AS frontend
WORKDIR /ui
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build          # -> /ui/dist

# --- Stage 2: the app ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
# Built SPA is served from app/static (see app/main.py).
COPY --from=frontend /ui/dist ./app/static

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
