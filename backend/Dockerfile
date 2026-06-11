FROM python:3.11-slim

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive
ARG TARGETARCH

RUN sed -i 's|http://deb.debian.org|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl xz-utils libgomp1 \
    && case "${TARGETARCH}" in \
        arm64) ffmpeg_arch=arm64 ;; \
        amd64) ffmpeg_arch=amd64 ;; \
        *) echo "Unsupported TARGETARCH: ${TARGETARCH}" && exit 1 ;; \
       esac \
    && curl -fsSL "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-${ffmpeg_arch}-static.tar.xz" -o /tmp/ffmpeg.tar.xz \
    && tar -xf /tmp/ffmpeg.tar.xz -C /tmp \
    && mv /tmp/ffmpeg-*-static/ffmpeg /usr/local/bin/ \
    && mv /tmp/ffmpeg-*-static/ffprobe /usr/local/bin/ \
    && rm -rf /tmp/ffmpeg* \
    && apt-get purge -y curl xz-utils \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=600 \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch>=2.1.0" \
    && pip install --no-cache-dir --default-timeout=600 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn \
        -r requirements.txt

RUN pip install --no-cache-dir --default-timeout=600 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn \
        "peft>=0.10.0"

RUN pip install --no-cache-dir --default-timeout=600 \
        -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
        "paddlepaddle==3.0.0"

# FlagEmbedding 1.2.11 omits `from typing import Optional` in trainer.py
RUN python - <<'PY'
from pathlib import Path
trainer = Path("/usr/local/lib/python3.11/site-packages/FlagEmbedding/BGE_M3/trainer.py")
text = trainer.read_text()
if "from typing import Optional" not in text:
    trainer.write_text("from typing import Optional\n" + text)
PY

COPY app ./app

EXPOSE 8000
