FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git tzdata ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backtesting/ backtesting/
COPY config/ config/
COPY config.py .
COPY engines/ engines/
COPY scanner/ scanner/
COPY scripts/ scripts/
COPY services/ services/
COPY strategies/ strategies/
COPY utils/ utils/
COPY web/ web/

ENV PYTHONPATH=/app
ENV TZ=Asia/Kolkata
