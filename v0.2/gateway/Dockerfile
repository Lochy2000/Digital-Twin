# Ingestion gateway image. Only the gateway code goes in; the asset model and mappings
# are mounted read-only from v0.1 (see docker-compose.yml), so editing a mapping file
# needs a restart, not a rebuild.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt     # runtime only; tests use requirements-dev.txt
COPY gateway/ gateway/
ENV MODEL_DIR=/model
# Run as an ordinary user, not root: "If a service can run without privileges, use USER
# to change to a non-root user" (Docker build best practices,
# https://docs.docker.com/build/building/best-practices/#user).
RUN useradd --system --no-create-home gateway
USER gateway
CMD ["python", "-u", "-m", "gateway.service"]
