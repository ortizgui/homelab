FROM alpine:3.19

# Install dependencies
RUN apk add --no-cache \
    ca-certificates \
    tzdata \
    curl \
    bash \
    coreutils \
    findutils \
    util-linux \
    jq \
    && rm -rf /var/cache/apk/*

# Install restic
ARG RESTIC_VERSION=0.16.4
RUN case "$(uname -m)" in \
        x86_64) ARCH=amd64 ;; \
        aarch64) ARCH=arm64 ;; \
        armv7l) ARCH=arm ;; \
        *) echo "Unsupported architecture: $(uname -m)" && exit 1 ;; \
    esac \
    && curl -L "https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_${ARCH}.bz2" \
        -o restic.bz2 \
    && bunzip2 restic.bz2 \
    && chmod +x restic \
    && mv restic /usr/local/bin/ \
    && restic version

# Install rclone
ARG RCLONE_VERSION=1.65.2
RUN case "$(uname -m)" in \
        x86_64) ARCH=amd64 ;; \
        aarch64) ARCH=arm64 ;; \
        armv7l) ARCH=arm-v7 ;; \
        *) echo "Unsupported architecture: $(uname -m)" && exit 1 ;; \
    esac \
    && curl -L "https://github.com/rclone/rclone/releases/download/v${RCLONE_VERSION}/rclone-v${RCLONE_VERSION}-linux-${ARCH}.zip" \
        -o rclone.zip \
    && unzip rclone.zip \
    && mv rclone-*/rclone /usr/local/bin/ \
    && rm -rf rclone* \
    && rclone version

# Create directories
RUN mkdir -p /scripts /var/log/backup /backup-sources

# Set working directory
WORKDIR /scripts

# Copy scripts
COPY scripts/ /scripts/
RUN chmod +x /scripts/*.sh

# Create non-root user for security
RUN adduser -D -s /bin/bash backup
USER backup

# Health check
HEALTHCHECK --interval=6h --timeout=30s --start-period=10s --retries=3 \
    CMD ["/scripts/healthcheck.sh"]

CMD ["tail", "-f", "/dev/null"]