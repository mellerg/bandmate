# ── Stage 1: build the frontend ───────────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python runtime + built frontend ──────────────────────────────────
FROM python:3.11-slim

# aubio needs gcc + headers to compile from source
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        build-essential \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
# CFLAGS workaround: aubio 0.4.9 has a function-pointer type mismatch
# against newer numpy that clang/gcc flag as an error on stricter builds.
COPY backend/requirements.txt ./backend/
RUN CFLAGS="-Wno-error=incompatible-function-pointer-types" \
    pip install --no-cache-dir -r backend/requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend from stage 1
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

EXPOSE 8000

# Run from the backend directory so relative imports resolve correctly
CMD ["sh", "-c", "cd /app/backend && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
