# Homelab

Coleção de serviços e automações para operação de homelab, com foco em backup, monitoramento de discos e acesso remoto seguro.

## Visão Geral

Este repositório centraliza componentes independentes, mas complementares, para um ambiente self-hosted:

- `cloud_backup`: stack de backup criptografado com `restic + rclone`, API local, agendamento e interface web.
- `disk-health`: monitoramento de discos e RAID com SMART, `mdadm` e alertas no Telegram.
- `tailscale`: acesso remoto seguro à rede local via Tailscale em Docker.
- `tailscale_isolated`: variação enxuta do setup Tailscale para cenários isolados.

## Funcionalidades

- Backup criptografado com validações de segurança antes de qualquer alteração em nuvem.
- Agendamento de rotinas de backup, retenção e prune.
- Monitoramento de saúde de discos com alertas automáticos.
- Exposição segura da LAN via VPN sem abrir portas na internet.
- Organização modular, com documentação própria por serviço.

## Estrutura Do Projeto

```text
homelab/
├── cloud_backup/        # Backup com restic + rclone + web UI
├── diagnostics/         # Espaço reservado para diagnósticos e utilitários
├── disk-health/         # Monitor SMART/RAID com alertas
├── tailscale/           # Tailscale com subnet router/exit node
└── tailscale_isolated/  # Variante simplificada do Tailscale
```

## Pré-Requisitos

Os requisitos variam por módulo, mas este repositório assume, em geral:

- Docker e Docker Compose para os serviços em contêiner.
- Linux para os componentes que dependem de `/proc`, SMART, `mdadm` ou `systemd`.
- `smartmontools`, `mdadm`, `jq` e `curl` para o módulo `disk-health`.
- Conta e credenciais válidas para:
  - provedor de storage compatível com `rclone`
  - bot do Telegram, se alertas estiverem habilitados
  - Tailscale, para os módulos de VPN

## Início Rápido

Escolha o módulo que deseja subir e siga o fluxo correspondente.

### Cloud Backup

```bash
cd /Volumes/homeX/git/homelab/cloud_backup
cp .env.example .env
./setup.sh
docker compose up -d --build
```

Depois, acesse:

- Web UI: [http://localhost:8095](http://localhost:8095)
- API: [http://localhost:8096](http://localhost:8096)

### Disk Health

```bash
cd /Volumes/homeX/git/homelab/disk-health
sudo install -m 0600 disk-alert.conf /etc/disk-alert.conf
sudo install -m 0755 disk-health.sh /usr/local/sbin/disk-health.sh
sudo /usr/local/sbin/disk-health.sh --test
```

### Tailscale

```bash
cd /Volumes/homeX/git/homelab/tailscale
cp .env.example .env
docker compose up -d
```

## Configurações

Esta seção resume os principais arquivos e variáveis usados em cada módulo.

### Cloud Backup

Arquivo principal:

- [`cloud_backup/.env`](/Volumes/homeX/git/homelab/cloud_backup/.env)

Parâmetros mais importantes:

| Variável | Descrição |
| --- | --- |
| `CLOUD_BACKUP_WEB_PORT` | Porta exposta pela interface web |
| `CLOUD_BACKUP_API_PORT` | Porta exposta pela API |
| `CLOUD_BACKUP_DATA_DIR` | Diretório persistente com config, logs, cache e restore |
| `TZ` | Fuso horário dos serviços |
| `CLOUD_BACKUP_HOSTNAME` | Nome lógico do host monitorado |
| `PRIMARY_SOURCE_PATH` | Caminho principal no host para backup |
| `SECONDARY_SOURCE_PATH` | Caminho secundário no host para backup |
| `RESTIC_REPOSITORY` | Repositório remoto usado pelo `restic` |
| `RESTIC_PASSWORD` | Senha do repositório `restic` |
| `BANDWIDTH_LIMIT` | Limite de upload |
| `TELEGRAM_BOT_TOKEN` | Token do bot para notificações |
| `TELEGRAM_CHAT_ID` | Chat ID do destino das notificações |
| `WEBHOOK_URL` | Endpoint alternativo para alertas |

Persistência esperada em `CLOUD_BACKUP_DATA_DIR`:

- `config/config.json`
- `logs/`
- `rclone/rclone.conf`
- `restic-cache/`
- `restore/`
- `state/`

### Disk Health

Arquivo principal:

- `/etc/disk-alert.conf`

Parâmetros mais importantes:

| Variável | Descrição |
| --- | --- |
| `TELEGRAM_TOKEN` | Token do bot do Telegram |
| `TELEGRAM_CHAT_ID` | Identificador do chat que receberá os alertas |
| `HDD_WARN_TEMP` | Temperatura de aviso para HDD |
| `HDD_CRIT_TEMP` | Temperatura crítica para HDD |
| `SSD_WARN_TEMP` | Temperatura de aviso para SSD |
| `SSD_CRIT_TEMP` | Temperatura crítica para SSD |
| `MAP_DEVICE_OPTS` | Opções extras por disco, útil para bridges USB-SATA |
| `DISKS` | Lista manual de discos monitorados |

### Tailscale

Arquivo principal:

- [`tailscale/.env`](/Volumes/homeX/git/homelab/tailscale/.env)

Parâmetros mais importantes:

| Variável | Descrição |
| --- | --- |
| `TS_AUTHKEY` | Chave de autenticação do nó |
| `TS_HOSTNAME` | Nome do dispositivo na malha Tailscale |
| `TS_EXTRA_ARGS` | Flags extras, como subnet router, exit node e DNS |

Exemplo comum de `TS_EXTRA_ARGS`:

```ini
TS_EXTRA_ARGS=--advertise-exit-node --advertise-routes=192.168.68.0/24 --accept-dns=false
```

## Exemplos

### Exemplo 1: Backup com persistência fora do repositório

```env
# cloud_backup/.env
CLOUD_BACKUP_DATA_DIR=/mnt/m2/docker/cloud_backup
CLOUD_BACKUP_WEB_PORT=8095
CLOUD_BACKUP_API_PORT=8096
TZ=America/Sao_Paulo
RESTIC_REPOSITORY=rclone:gdrive:/backups/restic
BANDWIDTH_LIMIT=4M
```

### Exemplo 2: Teste do monitoramento de discos

```bash
cd /Volumes/homeX/git/homelab/disk-health
sudo /usr/local/sbin/disk-health.sh --test
journalctl -t disk-health -n 50 --no-pager
```

### Exemplo 3: Tailscale com acesso à LAN

```env
# tailscale/.env
TS_AUTHKEY=tskey-auth-xxxxxxxxxxxxxxxx
TS_HOSTNAME=orangepi
TS_EXTRA_ARGS=--advertise-routes=192.168.68.0/24 --accept-dns=false
```

### Exemplo 4: Tailscale como exit node

```env
# tailscale/.env
TS_AUTHKEY=tskey-auth-xxxxxxxxxxxxxxxx
TS_HOSTNAME=orangepi
TS_EXTRA_ARGS=--advertise-exit-node --advertise-routes=192.168.68.0/24 --accept-dns=false
```

## Documentação Por Módulo

Cada componente possui documentação específica:

- [`cloud_backup/README.md`](/Volumes/homeX/git/homelab/cloud_backup/README.md)
- [`cloud_backup/DIRECTORY_STRUCTURE.md`](/Volumes/homeX/git/homelab/cloud_backup/DIRECTORY_STRUCTURE.md)
- [`disk-health/README.md`](/Volumes/homeX/git/homelab/disk-health/README.md)
- [`tailscale/README.md`](/Volumes/homeX/git/homelab/tailscale/README.md)

## Segurança

- Não versione arquivos `.env` com segredos reais.
- Revogue e regenere credenciais expostas acidentalmente.
- Restrinja permissões de arquivos com tokens, chaves e senhas.
- Revise cuidadosamente paths monitorados e pontos de montagem antes de habilitar backups automáticos.

## Contribuição

Sugestão de fluxo para contribuições:

1. Crie uma branch para a alteração.
2. Atualize código e documentação no mesmo conjunto de mudanças.
3. Valide localmente o módulo afetado.
4. Abra um pull request com contexto, impacto e passos de teste.

## Status Do Projeto

Este repositório está em uso prático para automação de homelab e reúne projetos com diferentes níveis de maturidade. Consulte a documentação de cada módulo para detalhes operacionais e limitações conhecidas.

## Licença

Nenhuma licença foi definida atualmente neste repositório. Se a intenção for distribuição pública como projeto open source, o ideal é adicionar um arquivo `LICENSE` antes de reutilização por terceiros.
