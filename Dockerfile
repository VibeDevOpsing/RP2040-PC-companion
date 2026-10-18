FROM python:3.12-slim

LABEL org.opencontainers.image.title="RP2040-Zero Desk-Buddy Host Daemon"
LABEL org.opencontainers.image.description="Containerized host daemon for the RP2040-Zero 8-Bit Snow Bear companion"

# Install lightweight X11 / Wayland sensor & screenshot utilities for Linux host passthrough
RUN apt-get update && apt-get install -y --no-install-recommends \
    xdotool \
    x11-utils \
    xprintidle \
    scrot \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY host_companion.py .

ENV IN_DOCKER=1
ENV PYTHONUNBUFFERED=1
ENV LMSTUDIO_URL="http://host.docker.internal:1234/v1"

ENTRYPOINT ["python3", "host_companion.py"]
