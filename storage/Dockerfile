FROM python:3.11-slim
WORKDIR /app
COPY storage_subscriber.py .
RUN pip install paho-mqtt influxdb-client
CMD ["python", "storage_subscriber.py"]