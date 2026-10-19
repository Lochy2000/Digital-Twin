# Ingestion gateway image. Only the gateway code goes in; the asset model and mappings
# are mounted read-only from v0.1 (see docker-compose.yml), so editing a mapping file
# needs a restart, not a rebuild.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gateway/ gateway/
ENV MODEL_DIR=/model
CMD ["python", "-u", "-m", "gateway.service"]
