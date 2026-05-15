FROM debian:bookworm-slim

# MakeMKV build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libc6-dev \
    libssl-dev \
    libexpat1-dev \
    libavcodec-dev \
    libgl1-mesa-dev \
    qtbase5-dev \
    zlib1g-dev \
    wget \
    curl \
    python3 \
    python3-pip \
    python3-venv \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install latest MakeMKV CLI
# Check https://www.makemkv.com/forum/viewtopic.php?f=3&t=224 for latest version
ARG MAKEMKV_VERSION=1.17.8
RUN wget -q "https://www.makemkv.com/download/makemkv-oss-${MAKEMKV_VERSION}.tar.gz" \
    "https://www.makemkv.com/download/makemkv-bin-${MAKEMKV_VERSION}.tar.gz" \
    && tar xzf "makemkv-oss-${MAKEMKV_VERSION}.tar.gz" \
    && tar xzf "makemkv-bin-${MAKEMKV_VERSION}.tar.gz" \
    && cd "makemkv-oss-${MAKEMKV_VERSION}" \
    && ./configure && make && make install \
    && cd "../makemkv-bin-${MAKEMKV_VERSION}" \
    && make && make install \
    && cd / && rm -rf makemkv-* \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY iso_watcher.py .

# Config is mounted at /config/config.yaml via docker-compose volume
ENV CONFIG_PATH=/config/config.yaml

CMD ["python3", "/app/iso_watcher.py"]
