# ── Stage 1: build the frontend ───────────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python runtime + built frontend ──────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies (librosa ships pre-built wheels — no compiler needed)
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend from stage 1
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

EXPOSE 8000

# Unbuffered output so logs appear immediately in Render dashboard
ENV PYTHONUNBUFFERED=1

# Run from the backend directory so relative imports resolve correctly
CMD ["sh", "-c", "cd /app/backend && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
