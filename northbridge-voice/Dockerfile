# ── Stage 1: build the browser client ─────────────────────────────────────
FROM node:22-alpine AS client
WORKDIR /client
COPY client/package.json client/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY client/ ./
RUN npm run build

# ── Stage 2: one Python process serves the page, /api/token and /ws ───────
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /app

COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/ server/
COPY --from=client /client/dist client/dist

USER 1001
EXPOSE 8080
# Code Engine terminates TLS in front of the app, so trust its forwarded
# headers (used for per-IP rate limiting of /api/token).
CMD ["sh", "-c", "uvicorn app:app --app-dir server --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
