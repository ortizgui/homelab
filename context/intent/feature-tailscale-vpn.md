# Feature: VPN Remote Access

## What
Secure remote access to the homelab LAN via Tailscale VPN running in Docker, supporting subnet routing for accessing all LAN devices, optional exit node functionality, and an isolated configuration for sandboxed environments.

## Why
Provide secure remote access to the local network (192.168.68.0/24) without opening ports on the internet, working behind double NAT or CGNAT. Enable accessing LAN services (Portainer, backups, etc.) from anywhere.

## Acceptance Criteria
- [ ] Tailscale runs in a Docker container with persistent state
- [ ] Subnet routing allows remote access to all devices on the LAN
- [ ] Exit node option available for routing all traffic through homelab
- [ ] Optional isolated configuration with read-only root and restricted capabilities
- [ ] IP forwarding enabled on the host
- [ ] Kernel networking enabled (TS_USERSPACE=false)

## Related
- [Decision: Tech Stack](../decisions/001-tech-stack.md)

## Status
- **Created**: 2026-05-03 (Phase: Intent)
- **Status**: Active (already implemented)
