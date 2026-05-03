# AGENTS.md

## Setup Commands
- Install (cloud_backup): `docker compose up -d --build` (run `./setup.sh` first)
- Install (netpulse): `docker compose up -d --build`
- Install (disk-health): `sudo ./update_install.sh` from `disk-health/`
- Install (tailscale): `docker compose up -d`
- Test (cloud_backup): `python3 -m unittest discover -s cloud_backup/tests`
- Test (netpulse): `python3 -m compileall netpulse/app`
- Compile check: `python3 -m compileall cloud_backup/app cloud_backup/tests`

## Code Style
- Python: `from __future__ import annotations`, type hints, dataclasses for config objects
- Bash: `set -eo pipefail`, modular functions, sourced config files
- Docker: Multi-stage builds avoided; single layer with runtime deps
- Frontend: Vanilla JS, no frameworks, inline SVG charts
- Follow patterns from `@context/knowledge/patterns/`

## Context Files to Load

Before starting any work, load relevant context:
- @context/intent/project-intent.md (always)
- @context/intent/feature-*.md (for specific feature)
- @context/decisions/*.md (relevant decisions)
- @context/knowledge/patterns/*.md (patterns to follow)

## Project Structure
```
root/
├── AGENTS.md
├── context/
│   ├── .context-mesh-framework.md
│   ├── intent/
│   ├── decisions/
│   ├── knowledge/
│   │   ├── patterns/
│   │   └── anti-patterns/
│   ├── agents/
│   └── evolution/
├── cloud_backup/        # Backup stack
├── diagnostics/         # Diagnostics utilities
├── disk-health/         # Disk monitoring
├── netpulse/            # Connectivity monitoring
├── tailscale/           # VPN subnet router
└── tailscale_isolated/  # VPN isolated mode
```

## AI Agent Rules

### Always
- Load context before implementing
- Follow decisions from @context/decisions/
- Use patterns from @context/knowledge/patterns/
- Update context after any changes

### Never
- Ignore documented decisions
- Use anti-patterns from @context/knowledge/anti-patterns/
- Leave context stale after changes

### After Any Changes (Critical)
AI must update Context Mesh after changes:
- Update relevant feature intent if functionality changed
- Add outcomes to decision files if approach differed
- Update changelog.md
- Create learning-*.md if significant insights

## Definition of Done (Build Phase)

Before completing any implementation:
- [ ] ADR exists before implementation
- [ ] Code follows documented patterns
- [ ] Decisions respected
- [ ] Tests passing
- [ ] Context updated to reflect changes
- [ ] Changelog updated
