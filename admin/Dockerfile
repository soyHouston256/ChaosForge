FROM python:3.12-slim
WORKDIR /app
COPY controller.py backend.py server.py faults.py observations.py experiments.py ./
COPY static ./static
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
# 8080 = observer (Tider), 8081 = admin (panel and ground truth).
EXPOSE 8080 8081
CMD ["python", "server.py", "--bind", "0.0.0.0", "--port", "8080", "--admin-port", "8081", "--data", "/data"]
