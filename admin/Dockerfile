FROM python:3.12-slim
WORKDIR /app
COPY controller.py backend.py server.py ./
COPY static ./static
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8080
CMD ["python", "server.py", "--bind", "0.0.0.0", "--data", "/data"]
