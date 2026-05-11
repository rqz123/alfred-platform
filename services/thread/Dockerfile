FROM python:3.11-slim

WORKDIR /service

# Install shared package
COPY shared /shared
RUN pip install --no-cache-dir -e /shared

# Install service dependencies
COPY services/nudge/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY services/nudge/ ./

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
