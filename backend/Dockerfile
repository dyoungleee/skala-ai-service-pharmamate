FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PHARMAMATE_DATA_DIR=/data

WORKDIR /app

COPY requirements-api.txt ./requirements-api.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements-api.txt

COPY backend ./backend

RUN groupadd --system --gid 10001 pharmamate \
    && useradd --system --uid 10001 --gid pharmamate --home-dir /app pharmamate \
    && mkdir -p /data \
    && chown pharmamate:pharmamate /data

USER pharmamate

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
