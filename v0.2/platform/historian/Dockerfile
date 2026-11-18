# Historian image. Build context: v0.2/ (see platform/compose.yml), so it can install ../common.
# The asset model is mounted at run time (/model); the contracts come with dtteo_common.
FROM python:3.11-slim
WORKDIR /app
COPY platform/historian/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Shared package. After the repo split:  pip install "git+<repo url>@<tag>#subdirectory=common"
COPY common/ /tmp/common/
RUN pip install --no-cache-dir /tmp/common && rm -rf /tmp/common
COPY platform/historian/historian/ historian/
ENV MODEL_DIR=/model
RUN useradd --system --no-create-home historian
USER historian
CMD ["python", "-u", "-m", "historian.service"]
