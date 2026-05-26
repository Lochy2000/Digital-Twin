FROM python:3.11-slim
WORKDIR /app
COPY publisher.py .
RUN pip install paho-mqtt
CMD ["python", "publisher.py"]