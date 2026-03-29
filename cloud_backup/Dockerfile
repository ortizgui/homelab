FROM alpine:3.21

ARG RESTIC_VERSION=0.17.3
ARG RCLONE_VERSION=1.69.2

RUN apk add --no-cache \
    bash \
    ca-certificates \
    coreutils \
    curl \
    jq \
    python3 \
    py3-pip \
    py3-setuptools \
    tzdata \
    util-linux \
    findutils \
    grep \
    sed \
    tar \
    unzip

RUN case "$(uname -m)" in \
        x86_64) RESTIC_ARCH=amd64 ; RCLONE_ARCH=amd64 ;; \
        aarch64) RESTIC_ARCH=arm64 ; RCLONE_ARCH=arm64 ;; \
        armv7l) RESTIC_ARCH=arm ; RCLONE_ARCH=arm-v7 ;; \
        *) echo "Unsupported architecture: $(uname -m)" && exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_${RESTIC_ARCH}.bz2" -o /tmp/restic.bz2 \
    && bunzip2 /tmp/restic.bz2 \
    && install -m 0755 /tmp/restic /usr/local/bin/restic \
    && curl -fsSL "https://github.com/rclone/rclone/releases/download/v${RCLONE_VERSION}/rclone-v${RCLONE_VERSION}-linux-${RCLONE_ARCH}.zip" -o /tmp/rclone.zip \
    && unzip -q /tmp/rclone.zip -d /tmp \
    && install -m 0755 /tmp/rclone-v${RCLONE_VERSION}-linux-${RCLONE_ARCH}/rclone /usr/local/bin/rclone \
    && rm -rf /tmp/restic /tmp/rclone.zip /tmp/rclone-v${RCLONE_VERSION}-linux-${RCLONE_ARCH}

RUN mkdir -p /workspace/app /scripts /data/config /data/logs /data/rclone /data/restic-cache /data/state /source /health /host/proc

ENV PYTHONUNBUFFERED=1
ENV CLOUD_BACKUP_CONFIG_FILE=/data/config/config.json
ENV CLOUD_BACKUP_STATE_DIR=/data/state
ENV CLOUD_BACKUP_LOG_DIR=/data/logs
ENV CLOUD_BACKUP_RCLONE_CONFIG=/data/rclone/rclone.conf
ENV RESTIC_CACHE_DIR=/data/restic-cache

WORKDIR /workspace

COPY app/ /workspace/app/
COPY scripts/ /scripts/
COPY pyproject.toml /workspace/pyproject.toml

RUN python3 -m pip install --break-system-packages --no-cache-dir /workspace \
    && python3 -c "import app.api_server; import app.engine_server; import app.scheduler" \
    && chmod +x /scripts/*.sh

CMD ["python3", "-m", "app.engine_server"]
