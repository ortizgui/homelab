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
- AI-first development: minimize file fragmentation, reduce cognitive load and token use, keep related logic close, favor fast understanding and iteration, avoid over-engineering.
- Prefer simplicity over complexity, readability over cleverness, maintainability over theoretical purity, fast iteration over rigid structure, practical solutions over academic design.
- Use KISS, YAGNI, and DRY without premature abstraction.
- Treat Clean Code and Object Calisthenics as guidance, not dogma.
- Prefer fewer files with cohesive responsibility. Split only when a file becomes hard to read, a component is truly reusable, or a real domain boundary exists.
- Avoid deep folders and excessive layers (controller → service → usecase → handler → mapper → utils).
- Keep business logic inline or near-inline when small. Extract only when complexity grows.
- Avoid boilerplate, over-layering, indirection, artificial abstractions, interface overuse, hidden side effects, and magic values.
- Code in English with descriptive names.
- Validate inputs at boundaries, raise meaningful errors.
- Use small functions, early returns, direct data structures.
- Comments explain why, not what code does.
- Python: `from __future__ import annotations`, type hints, dataclasses for config objects
- Bash: `set -eo pipefail`, modular functions, sourced config files
- Docker: Multi-stage builds avoided; single layer with runtime deps
- Frontend: Vanilla JS, no frameworks, inline SVG charts
- Follow patterns from `@context/knowledge/patterns/`

## Response Style
- Caveman mode active by default for every response.
- Default intensity: full.
- Stop caveman only when user says `stop caveman` or `normal mode`.
- Switch intensity with `/caveman lite`, `/caveman full`, `/caveman ultra`.
- Drop articles, filler, pleasantries, hedging unless clarity requires them.
- Use fragments when clear, short synonyms, exact technical terms.
- Keep code blocks, commands, file paths, function names, API names, error strings exact.
- Pattern: `[thing] [action] [reason]. [next step].`
- Temporarily drop caveman for security warnings, irreversible action confirmations, ambiguous multi-step sequences, or when compression creates technical ambiguity.
- Resume caveman after clear part done.
- Write code, commits, PRs in normal professional style.

## Context Files to Load

Before starting any work, load relevant context:
- @context/.context-mesh-framework.md (always)
- @context/intent/project-intent.md (always)
- @context/intent/feature-*.md (for specific feature)
- @context/decisions/*.md (relevant decisions)
- @context/knowledge/patterns/*.md (patterns to follow)
- @context/evolution/changelog.md (before and after changes)

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
- Load Context Mesh before implementing.
- Respect separation of feature, decision, and pattern files.
- Keep feature docs high-level: what and why only.
- Keep technical choices in decision files.
- Keep code examples in pattern files.
- Follow decisions from @context/decisions/
- Use patterns from @context/knowledge/patterns/
- Update context after any changes.
- Run tests after code changes to catch regressions.

### Never
- Ignore documented decisions.
- Put implementation details, library names, file paths, or code examples in feature files.
- Use anti-patterns from @context/knowledge/anti-patterns/
- Leave context stale after changes.
- Hardcode secrets.

### After Any Changes (Critical)
AI must update Context Mesh after changes:
- Update relevant feature intent if functionality changed.
- Add or update decision files if technical approach changed.
- Add or update pattern files if implementation conventions changed.
- Add outcomes to decision files if accepted approach produced new learnings.
- Update changelog.md.
- Create learning-*.md if significant insight to preserve.
- Run tests: `python3 -m unittest discover -s cloud_backup/tests` and/or `python3 -m compileall netpulse/app`. Fix failures before marking done.

## Definition of Done (Build Phase)

Before completing any implementation:
- [ ] Relevant context loaded
- [ ] ADR exists before implementation when technical choice involved
- [ ] Code follows documented patterns
- [ ] Decisions respected
- [ ] Tests passing or verification notes documented
- [ ] Context updated to reflect changes
- [ ] Changelog updated
