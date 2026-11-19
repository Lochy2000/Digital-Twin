# Historian image. Build context: v0.2/ (see platform/compose.yml), so it can install ../common.
# The asset model is mounted at run time (/model); the contracts come with dtteo_common.
FROM python:3.11-slim
WORKDIR /app
COPY platform/historian/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Shared code (mapper, units, log format, contracts): copied in as plain files, not
# pip-installed, so the build needs no download and no build tools (works offline, e.g. on
# a Pi in the field). Same layout as the installed package: dtteo_common/ with contracts/ inside.
COPY common/dtteo_common/ dtteo_common/
COPY common/contracts/ dtteo_common/contracts/
COPY platform/historian/historian/ historian/
ENV MODEL_DIR=/model
RUN useradd --system --no-create-home historian
USER historian
CMD ["python", "-u", "-m", "historian.service"]
