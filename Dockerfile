FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /src

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential tzdata \
    && ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime \
    && echo "Europe/Berlin" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --target=/install -r requirements.txt \
    && python -m pip install --target=/install --upgrade soupsieve urllib3

COPY . /src

FROM gcr.io/distroless/python3:latest as runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy installed Python packages and source from builder
COPY --from=builder /install /usr/local
COPY --from=builder /src /app

# Distroless minimal runtime; run as root (no user utilities available)
EXPOSE 8080 8765

CMD ["python3", "main.py"]
