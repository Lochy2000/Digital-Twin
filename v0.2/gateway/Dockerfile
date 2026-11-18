# Ingestion gateway image. Build context: v0.2/ (see gateway/compose.yml), so it can install
# ../common. The asset model and mappings are mounted at run time (/model), not built in.
FROM python:3.11-slim
WORKDIR /app
COPY gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt     # runtime only; tests use requirements-dev.txt
# Shared package (mapper, units, contracts, logfmt). After the repo split this becomes
#   RUN pip install --no-cache-dir "git+<repo url>@<tag>#subdirectory=common"
COPY common/ /tmp/common/
RUN pip install --no-cache-dir /tmp/common && rm -rf /tmp/common
COPY gateway/gateway/ gateway/
ENV MODEL_DIR=/model
# Run as an ordinary user, not root (Docker build best practices:
# https://docs.docker.com/build/building/best-practices/#user).
RUN useradd --system --no-create-home gateway
USER gateway
CMD ["python", "-u", "-m", "gateway.service"]
