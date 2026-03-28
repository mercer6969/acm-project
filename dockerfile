# ═══════════════════════════════════════════════════════════
#  ACM — Multi-stage Dockerfile
# ═══════════════════════════════════════════════════════════

# ── Stage 1: Build React frontend ────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ .
RUN npm run build
# Output: /frontend/dist


# ── Stage 2: Python backend on ubun:22.04 ───────────────────────────────────
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /acm

# Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Backend source
COPY app/ ./app/
COPY ground_stations.csv .

# Built frontend from stage 1 → served as static files
COPY --from=frontend-builder /frontend/dist ./static/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]