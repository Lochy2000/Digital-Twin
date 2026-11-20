# dt-node image, for the dev setup on a laptop. On a real node (a Pi), dt-node runs as a plain
# Python service, no Docker: lighter on a 512 MB Pi Zero (setup packs, later).
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dtnode/ dtnode/
RUN useradd --system --no-create-home node && mkdir /data && chown node /data
USER node
CMD ["python", "-u", "-m", "dtnode.service", "/config/node.toml"]
