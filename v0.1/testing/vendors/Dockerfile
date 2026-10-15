FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
# Which vendor runs is chosen in docker-compose.yml with `command:`
CMD ["python", "acme_publisher.py"]
