FROM python:3.10-slim
WORKDIR /app
RUN pip install --no-cache-dir prometheus-client
COPY docker_exporter.py .
CMD ["python", "-u", "docker_exporter.py"]
