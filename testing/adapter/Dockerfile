FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install paho-mqtt pyyaml
CMD ["python", "adapter_service.py"]