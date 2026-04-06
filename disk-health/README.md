# disk-health — SMART & RAID monitor with Telegram alerts

Lightweight disk/RAID health monitor for Debian/Armbian (e.g., Orange Pi/RPi).  
 It checks SMART for all real disks (SATA/NVMe/USB-SAT), inspects Linux mdadm RAID, sends alerts to Telegram, and can answer Telegram commands for disk and backup status.

---

## Features

- Auto-discovers disks (filters out zram/mtdblock by default).
- SMART health, temperature thresholds (HDD/SSD), key attributes:
  - Reallocated_Sector_Ct, Current_Pending_Sector, Offline_Uncorrectable
- mdadm RAID status (`/proc/mdstat` + `mdadm --detail`), detects degraded arrays.
- Telegram alerts (Markdown), with anti-spam (only notifies on state changes).
- Telegram bot mode with keyboard shortcuts for disk health and backup status.
- Systemd service + timer (runs on boot and every 15 minutes).
- Optional weekly SMART self-tests.

---

## 1) Create your Telegram Bot

1. In Telegram, talk to **@BotFather** → `/newbot`
   - Choose a name and a unique username (must end with `bot`).
   - BotFather will return the **HTTP API token** (example: `123456:ABCDEF...`).  
     This is your **TELEGRAM_TOKEN**.

2. **Start a chat** with your new bot (send a “hi” or `/start`), otherwise it can’t message you.

### Find your `CHAT_ID` (two options)

- **Option A — @userinfobot (easiest)**  
  1. Open **@userinfobot** and it will reply with your user info:  
     `Id: 123456789` ← that is your **CHAT_ID**.

- **Option B — API `getUpdates`**  
  1. Send any message to your bot.  
  2. Open in your browser:  
     `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`  
     Look for: `"chat": { "id": 123456789, ... }` ← use this `id` as **CHAT_ID**.  
     (For groups, add the bot to the group and read the `chat.id` — it’s usually **negative** like `-1001234567890`.)

### Quick test with curl

```bash
TELEGRAM_TOKEN="123456:ABCDEF..."
TELEGRAM_CHAT_ID="123456789"

curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -d chat_id="$TELEGRAM_CHAT_ID" \
  -d parse_mode="Markdown" \
  --data-urlencode "text=Hello from *disk-health*"
```

You should receive the message in Telegram.

## 2) Install dependencies

````bash
sudo apt update
sudo apt install -y smartmontools jq mdadm curl
````

## 3) Files in this repo

```bash
.
├─ disk-health.sh                 # main checker
├─ telegram-bot.sh                # interactive Telegram bot poller
├─ smart-selftest-short.sh        # (optional) weekly SMART short test
├─ disk-alert.conf               # config file (to be copied to /etc/disk-alert.conf)
├─ disk-health.service
├─ disk-health.timer
├─ telegram-bot.service
├─ telegram-bot.timer
├─ smart-selftest-short.service
├─ smart-selftest-short.timer
└─ README.md
```

> You can deploy with a simple copy or create your own install.sh to place files in the paths below.

## 4) Configure

Create the config file with your token/chat and desired thresholds:

/etc/disk-alert.conf
```bash
# === Telegram ===
TELEGRAM_TOKEN="123456:ABCDEF..."   # required
TELEGRAM_CHAT_ID="123456789"        # required

# Script called by the Telegram bot to fetch backup status
#BACKUP_STATUS_SCRIPT="/usr/local/bin/cloud-backup-status.sh"

# Temperature thresholds (°C)
HDD_WARN_TEMP=55
HDD_CRIT_TEMP=60
SSD_WARN_TEMP=65
SSD_CRIT_TEMP=70

# (Optional) Force device options for certain USB docks (SAT)
# Example: "sda=-d sat sdb=-d sat"
#MAP_DEVICE_OPTS="sda=-d sat sdb=-d sat"

# (Optional) Manually pin devices; leave unset for auto-discovery
#DISKS="/dev/sda /dev/sdb /dev/nvme0n1"
```

> USB Dock note (Orico/Ugreen/etc.): Many USB-SATA bridges require -d sat for SMART. Use MAP_DEVICE_OPTS above if any disk returns “SMART not readable”.

## 5) Install scripts & systemd units

```bash
# config file
sudo install -m 0600 disk-alert.conf /etc/disk-alert.conf

# scripts
sudo install -m 0755 disk-health.sh /usr/local/sbin/disk-health.sh
sudo install -m 0755 telegram-bot.sh /usr/local/sbin/telegram-bot.sh
sudo install -m 0755 smart-selftest-short.sh /usr/local/sbin/smart-selftest-short.sh

# systemd
sudo install -m 0644 disk-health.service /etc/systemd/system/disk-health.service
sudo install -m 0644 disk-health.timer   /etc/systemd/system/disk-health.timer
sudo install -m 0644 telegram-bot.service /etc/systemd/system/telegram-bot.service
sudo install -m 0644 telegram-bot.timer   /etc/systemd/system/telegram-bot.timer
sudo install -m 0644 smart-selftest-short.service /etc/systemd/system/smart-selftest-short.service
sudo install -m 0644 smart-selftest-short.timer   /etc/systemd/system/smart-selftest-short.timer

sudo systemctl daemon-reload
```

Enable periodic checks (every 15 min + on boot):

```bash
sudo systemctl enable --now disk-health.timer
sudo systemctl enable --now telegram-bot.timer
```

(Optional) Enable weekly SMART short tests (Sunday 03:00):
```bash
sudo systemctl enable --now smart-selftest-short.timer
```

## 6) Run a test now

```bash
# Envia uma mensagem de teste para validar a configuração
sudo /usr/local/sbin/disk-health.sh --test

# Envia uma mensagem mesmo se o último hash for igual (força o envio)
sudo /usr/local/sbin/disk-health.sh --test --f

# Verificar logs do sistema
journalctl -t disk-health -n 50 --no-pager
```

### Parâmetros disponíveis:

- `--test`: Envia uma mensagem de teste para validar se a configuração do Telegram está funcionando
- `--test --f`: Força o envio da mensagem mesmo que o último estado seja igual (ignora o controle de hash)
- `--report`: Apenas imprime o relatório atual em Markdown, sem enviar alerta
- Sem parâmetros: Execução normal (apenas envia alerta em caso de mudança de estado)

## Telegram bot commands

After enabling `telegram-bot.timer`, the same bot can answer:

- `/start` or `/help`: show available actions and the Telegram keyboard
- `/disks`: return the current disk health report
- `/backup`: return the current backup status; if no backup is running, it returns the latest recorded backup result

The keyboard buttons `Saude dos discos` and `Status do backup` trigger the same actions.

**Nota importante**: Este script foi desenvolvido para sistemas Linux (Debian/Ubuntu/Armbian) onde os discos são nomeados como `/dev/sda`, `/dev/sdb`, `/dev/nvme0n1`, etc. Se você está testando no macOS, os discos sda/sdb/sdc não existem, por isso aparecem sem % de uso. O script funcionará corretamente quando executado no sistema Linux de destino.

### Exemplo de mensagem de teste:

```
🧪 Teste do Disk Health - hostname

✅ Sistema de monitoramento funcionando corretamente

📊 Discos Monitorados:
sda: ✅ OK | 23% | 45°C
sdb: ⚠️ ALTA (58°C) | 67% | 58°C
nvme0n1: ✅ OK | 15% | 42°C

✅ Status: Nenhum problema detectado

🕐 Teste: 2025-09-07 00:31:47
```

### Exemplo de mensagem de alerta:

```
🚨 Disk Alert - hostname

📊 Status dos Discos:
sda: ❌ FAILING_NOW | 23% | 65°C
sdb: 🔥 CRÍTICA (72°C) | 67% | 72°C
nvme0n1: ✅ OK | 15% | 42°C

🔧 Problemas SMART:
sda: FAILING_NOW

🚨 Uso Crítico (≥85%):
/home (/dev/sda1) - 87%

⚠️ Uso Alto (≥70%):
/var (/dev/sdb2) - 75%
```

If RAID is degraded or any SMART critical attribute trips, you’ll see 🟡 WARN or 🔴 CRITICAL with reasons.

## 7) How it works (criteria)

	•	CRITICAL
    •	SMART overall FAIL
    •	Current_Pending_Sector > 0 or Offline_Uncorrectable > 0
    •	Temperature ≥ critical threshold
    •	mdadm RAID degraded ([U_]/[_U] or degraded)
	•	WARN
    •	Reallocated_Sector_Ct > 0
    •	Temperature ≥ warn threshold

The message includes a code block with /proc/mdstat and mdadm --detail output for quick diagnosis.

## 8) Notes: device discovery & exclusions

	•	The script auto-discovers real disks and ignores non-disk block devices like zram and mtdblock.
	•	You can explicitly control which devices are scanned via DISKS, or keep auto-mode and optionally force SAT for some USB devices using MAP_DEVICE_OPTS.

## 9) Troubleshooting

	•	No Telegram message
	  •	Verify config is loaded:
  
  ```bash
  sudo bash -c '. /etc/disk-alert.conf; echo "$TELEGRAM_TOKEN"; echo "$TELEGRAM_CHAT_ID"'
  ```

    •	Test direct:
  ```bash
  sudo bash -c '. /etc/disk-alert.conf; curl -sS "https://api.telegram.org/bot$TELEGRAM_TOKEN/getMe"'
  ```

    •	Make sure you started the chat with your bot; try:
  ```bash
  sudo bash -c '. /etc/disk-alert.conf; curl -sS -X POST "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" \
  -d chat_id="$TELEGRAM_CHAT_ID" -d text="test from curl"'
  ```

	•	Permission denied when executing the script
	  •	Ensure executable bit and directories are executable:
  ```bash
  sudo chmod 755 /usr/local/sbin/disk-health.sh
  ls -ld /usr /usr/local /usr/local/sbin
  ```

  •	Check if the filesystem is mounted with noexec:
  ```bash
  findmnt -no TARGET,OPTIONS /usr /usr/local
  ```

  If noexec, either remount with exec or move the script to /usr/local/bin.

	•	**unbound variable / set -u**
	  •	All locals must be initialized (status=""). The provided scripts already handle this.
	•	**Backticks cause nPersonalities: command not found**
	  •	When constructing Markdown code blocks, backticks must be in single-quoted or $'...' segments, not double-quoted. The scripts do this safely.
	•	**SMART not readable on USB disks**
	  •	Add SAT mapping in /etc/disk-alert.conf:

  ```bash
  MAP_DEVICE_OPTS="sda=-d sat sdb=-d sat"
  ```

## 10) Uninstall

  ```bash
  sudo systemctl disable --now disk-health.timer smart-selftest-short.timer
  sudo rm -f /etc/systemd/system/disk-health.service /etc/systemd/system/disk-health.timer
  sudo rm -f /etc/systemd/system/smart-selftest-short.service /etc/systemd/system/smart-selftest-short.timer
  sudo systemctl daemon-reload

  sudo rm -f /usr/local/sbin/disk-health.sh /usr/local/sbin/smart-selftest-short.sh
  sudo rm -rf /var/lib/disk-health
  # Keep or remove config:
  # sudo rm -f /etc/disk-alert.conf
  ```

## 11) Security

	•	/etc/disk-alert.conf contains secrets — restrict permissions:

  ```bash
  sudo chown root:root /etc/disk-alert.conf
  sudo chmod 600 /etc/disk-alert.conf
  ```
