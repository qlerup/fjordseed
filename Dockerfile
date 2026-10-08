FROM python:3.13-alpine@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a
RUN apk add --no-cache qbittorrent-nox=5.2.1-r0
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py hub.py runtime.py state.py qbit_rpc.py qbit_worker.py trackers.py ./
COPY templates ./templates
COPY static ./static
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8088
CMD ["python", "app.py"]
