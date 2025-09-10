# Homelab VPN with Tailscale (Docker)

This document explains how to set up a secure VPN on your homelab using **Tailscale** in Docker. The goal is to access your **entire home LAN** (e.g., `192.168.68.0/24`) remotely, without exposing ports to the internet, even when behind double NAT.

---

## 📌 Why Tailscale?

- Works behind **double NAT** and CGNAT (no port forwarding required).
- Built on **WireGuard** → secure and fast.
- **Subnet routing** → allows remote access to all devices in your LAN.
- **Exit node option** → you can route all your internet traffic through your homelab.

---

## 📂 Directory Structure

All files are stored in `/mnt/m2/docker/tailscale/`.

```
/mnt/m2/docker/tailscale/
├── docker-compose.yml
├── .env
└── state/            # Persistent Tailscale state
```

---

## 🚀 Setup Instructions

### 1. Generate an Auth Key

1.  Log into the Tailscale admin panel: [https://login.tailscale.com/admin/settings/keys](https://login.tailscale.com/admin/settings/keys)
2.  Click **Generate auth key**.
3.  Choose **Reusable** and optionally **Pre-approved**.
4.  Copy the generated key (e.g., `tskey-auth-xxxxxxxxxxxxxxxx`).
5.  Paste it into the `.env` file as described below.

### 2. Create Configuration Files

#### `.env`

Create a `.env` file with your Tailscale auth key and desired configuration.

```ini
# Tailscale Auth Key (generate from the admin panel)
TS_AUTHKEY=tskey-auth-xxxxxxxxxxxxxxxx

# Hostname for the Tailscale node
TS_HOSTNAME=orangepi

# Advertise routes to your local LAN and disable DNS overrides
TS_EXTRA_ARGS=--advertise-routes=192.168.68.0/24 --accept-dns=false
```

### 3. Enable IP Forwarding on the Host

Run these commands once on your host machine (e.g., your Orange Pi) to allow it to forward packets.

```bash
echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-tailscale.conf
echo "net.ipv6.conf.all.forwarding=1" | sudo tee -a /etc/sysctl.d/99-tailscale.conf
sudo sysctl --system
```

### 4. Start the Tailscale Container

```bash
cd /mnt/m2/docker/tailscale
docker compose up -d
```

### 5. Enable Subnet Routing in Tailscale

1.  Open the [**Machines** tab](https://login.tailscale.com/admin/machines) in your Tailscale admin panel.
2.  Find your new node (e.g., `orangepi`) and click on it.
3.  In the "Subnet routes" section, click **Review & Approve...** and approve the `192.168.68.0/24` route.
4.  On your client devices (laptop, phone), enable the "Use subnet routes" option for this node.

You can now access your LAN devices from anywhere. Example: `http://192.168.68.10:9000` (for Portainer).

---

## 🔒 Optional: Use as an Exit Node

To route all your internet traffic through your homelab (e.g., for secure browsing on public Wi-Fi), you can configure it as an exit node.

1.  **Update `.env`**:
    Add the `--advertise-exit-node` flag.

    ```ini
    TS_EXTRA_ARGS=--advertise-exit-node --advertise-routes=192.168.68.0/24 --accept-dns=false
    ```

2.  **Restart the container**:

    ```bash
    docker compose down
    docker compose up -d
    ```

3.  **Approve the Exit Node** in the Tailscale admin panel.
4.  On your client device, select the node and enable **Use exit node**.

---

## 🔐 Security Notes

-   **Do not commit `.env` to version control.** It contains your secret auth key.
-   If a key is ever exposed, revoke it immediately in the admin panel and generate a new one.
-   Enable 2FA on your Tailscale account for added security.

---

## 📚 References

-   [Tailscale Docs: Subnet Routers](https://tailscale.com/kb/1019/subnets)
-   [Tailscale Docs: Exit Nodes](https://tailscale.com/kb/1103/exit-nodes)
