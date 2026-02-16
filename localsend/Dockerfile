FROM debian:bookworm-slim

ARG LS_VERSION=1.17.0
ARG TARGETARCH

# Dependências mínimas pra rodar app Flutter/GTK em "modo headless" via Xvfb
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget xz-utils \
    xvfb \
    libgtk-3-0 libayatana-appindicator3-1 libegl1 \
    libx11-6 libxrandr2 libxcomposite1 libxi6 libxdamage1 libxfixes3 libxss1 libxtst6 \
    libnss3 libasound2 libdbus-1-3 libgbm1 libdrm2 libxkbcommon0 \
  && rm -rf /var/lib/apt/lists/*

# Baixa e instala o .deb oficial do GitHub Releases
RUN set -eux; \
  case "${TARGETARCH}" in \
    amd64)  DEB_ARCH="x86-64" ;; \
    arm64)  DEB_ARCH="arm-64" ;; \
    *) echo "Unsupported arch: ${TARGETARCH}"; exit 1 ;; \
  esac; \
  wget -O /tmp/localsend.deb "https://github.com/localsend/localsend/releases/download/v${LS_VERSION}/LocalSend-${LS_VERSION}-linux-${DEB_ARCH}.deb"; \
  apt-get update; \
  apt-get install -y /tmp/localsend.deb; \
  rm -f /tmp/localsend.deb; \
  rm -rf /var/lib/apt/lists/*

# Usuário sem root
RUN useradd -m -u 1000 localsend
USER localsend

ENV XDG_CONFIG_HOME=/data/config
ENV XDG_DATA_HOME=/data/config

WORKDIR /data

COPY --chown=localsend:localsend start.sh /start.sh
RUN chmod +x /start.sh

ENTRYPOINT ["/start.sh"]