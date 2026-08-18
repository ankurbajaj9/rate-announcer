FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /src

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install --target=/install -r requirements.txt

COPY . /src

FROM gcr.io/distroless/python3-debian12:latest AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/install:/app \
    TZ=Europe/Stockholm

WORKDIR /app

COPY --from=builder /install /install
COPY --from=builder /src /app

EXPOSE 8080 8765

CMD ["main.py"]
