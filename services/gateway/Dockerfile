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
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" sqlmodel pydantic-settings \
    "python-jose[cryptography]" python-multipart httpx

# Copy service source
COPY services/gateway/app ./app

# Copy built frontend so gateway can serve it
COPY --from=frontend-build /web/dist ./dist

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
