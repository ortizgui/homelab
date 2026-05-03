# Project Intent: Homelab

## What
Centralized collection of independent but complementary services and automations for operating a self-hosted homelab environment, including encrypted backups, disk/RAID monitoring, network connectivity monitoring, and secure remote access.

## Why
Provide a reliable, secure, and observable homelab infrastructure with:
- Encrypted offsite backups with safety guarantees against data corruption
- Early warning system for disk failures via SMART/RAID monitoring
- Internet connectivity visibility and DNS failure differentiation
- Secure remote LAN access without exposing ports to the internet

## Current State
Operational. All modules are in active use. Cloud Backup and Disk Health have cross-integration. Netpulse and Tailscale VPN are standalone services.

## Current Features
1. **Cloud Backup** - Encrypted backup stack (restic + rclone) with safety gates, scheduling, web UI, and API
2. **Disk Health Monitoring** - SMART health, temperature, and RAID monitoring with Telegram alerts
3. **Network Connectivity Monitoring (Netpulse)** - Dual-dimension (TCP + DNS) internet health monitoring with dashboard
4. **VPN Remote Access** - Tailscale-based secure remote LAN access with subnet routing and exit node options

## Status
- **Created**: 2026-05-03 (Phase: Intent)
- **Status**: Active
- **Note**: Generated from existing codebase analysis
