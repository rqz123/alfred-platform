# Stage 1: Build React frontend
FROM node:22-alpine AS frontend-build
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: Python gateway service
FROM python:3.11-slim

WORKDIR /service

# Install shared package
COPY shared /shared
RUN pip install --no-cache-dir -e /shared

# Install service dependencies
# Keep in sync with pyproject.toml [project.dependencies]
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    sqlmodel \
    "pydantic-settings" \
    "python-jose[cryptography]" \
    python-multipart \
    httpx \
    pyyaml \
    "openai>=1.0.0"

# Copy service source and service registry config
COPY services/gateway/app ./app
COPY config /config

# Copy built frontend so gateway can serve it
COPY --from=frontend-build /web/dist ./dist

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
