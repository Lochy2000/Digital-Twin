# Historian image. Built with the build context at v0.1/services (see docker-compose.yml) so it
# can include the gateway's code: the historian reuses gateway.mapper to read the asset model.
# The asset model, mappings and contracts are mounted read-only at run time.
FROM python:3.11-slim
WORKDIR /app
COPY historian/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ingestion-gateway/gateway/ gateway/
COPY historian/historian/ historian/
ENV MODEL_DIR=/model CONTRACTS_DIR=/contracts
RUN useradd --system --no-create-home historian
USER historian
CMD ["python", "-u", "-m", "historian.service"]
