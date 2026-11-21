# Ingestion gateway image. Build context: v0.2/ (see gateway/compose.yml), so it can install
# ../common. The asset model and mappings are mounted at run time (/model), not built in.
FROM python:3.11-slim
WORKDIR /app
COPY gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt     # runtime only; tests use requirements-dev.txt
# Shared code (mapper, units, log format, contracts): copied in as plain files, not
# pip-installed, so the build needs no download and no build tools (works offline, e.g. on
# a Pi in the field). Same layout as the installed package: dtteo_common/ with contracts/ inside.
COPY common/dtteo_common/ dtteo_common/
COPY common/contracts/ dtteo_common/contracts/
COPY gateway/gateway/ gateway/
ENV MODEL_DIR=/model
# Run as an ordinary user, not root (Docker build best practices:
# https://docs.docker.com/build/building/best-practices/#user).
RUN useradd --system --no-create-home gateway
USER gateway
# Healthy = heartbeat file under 90 s old and "ok" (dtteo_common/health.py, v0.2 step D2).
# Docker only reports it (docker compose ps); it doesn't restart an unhealthy container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=2 \
    CMD ["python", "-m", "dtteo_common.health", "/tmp/health.json", "90"]
CMD ["python", "-u", "-m", "gateway.service"]
