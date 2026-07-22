# Ansible Playbooks — Core

Ansible-based dev environment automation for multi-host workstation management (macOS + Linux).
User-home only, no sudo required. Generic base + "Jeff work" profile overlay.

## Architecture

```
ansible-playbooks/
├── bootstrap.sh              # one-liner: installs ansible, runs first playbook
├── ansible.cfg               # local connection, no become, smart fact caching
├── inventory/
│   ├── hosts                 # [macbooks], [linux], [workstations:children]
│   ├── group_vars/
│   │   ├── all.yml           # cross-cutting defaults (git, serena, paths)
│   │   ├── macbooks.yml      # macOS-specific vars (brew packages, launchd paths)
│   │   ├── linux.yml         # Linux-specific vars (apt packages, systemd paths)
│   │   ├── workstations.yml  # shared workstation vars
│   │   └── secrets.yml       # gitignored secrets (API keys, tokens)
│   └── host_vars/
│       ├── jeff-macbook.yml  # M4 Pro work machine specifics
│       └── betsy.yml         # NixOS desktop specifics
├── playbooks/
│   ├── base.yml              # generic dev machine setup (brew packages)
│   ├── work.yml              # Jeff's work profile (services, launchd agents)
│   ├── serena.yml            # serena_config.yml via Jinja2 template
│   ├── pi.yml                # Pi config (scaffold)
│   ├── omp.yml               # OMP config (scaffold)
│   ├── cursor.yml            # Cursor IDE config (scaffold)
│   └── drift.yml             # drift detection (--check --diff)
├── roles/
│   ├── base/tasks/           # shell, git, core CLI tools
│   ├── work/tasks/           # python, go, bun, ai-stack
│   ├── services/templates/   # launchd plists for serena project + MCP servers
│   ├── serena/templates/     # serena_config.yml.j2 (global config)
│   └── ides/templates/       # MCP configs for cursor, omp, pi
├── hooks/                    # (empty — placeholder for ansible hooks)
├── skills/                   # (empty — placeholder for custom skills)
├── serena-bulk-index.py      # bulk serena project indexer
├── serena-pending-index.txt  # projects needing manual index attention
└── indexed_projects.txt      # successfully indexed projects
```

## Key Invariants

- **User-home only**: everything under `~/`, no `/usr/local` or system paths. Corporate Mac constraint.
- **No sudo/become**: `become: false` everywhere. Use brew user mode, pipx, uv for tool installation.
- **Multi-OS**: macOS uses brew + launchd; Linux uses apt + systemd. Detection via `ansible_facts['os_family']`.
- **Idempotent**: all operations are idempotent — safe to run repeatedly.
- **Drift detection**: `drift.yml` runs all roles with `--check --diff` to detect configuration drift.
- **Serena config is dynamic**: `serena.yml` discovers git repos under `~/Projects/` via `ansible.builtin.find` and feeds them into `serena_config.yml` via Jinja2 template. Never hardcode project paths.
- **Secrets gitignored**: `inventory/group_vars/secrets.yml` and `local.yml` are in `.gitignore`.

## Companion Scripts

- **`serena-bulk-index.py`**: batch-index all discovered projects into Serena with auto language detection. Outputs `indexed_projects.txt` (success) and `serena-pending-index.txt` (failures). Can be restored via `ansible-playbook playbooks/serena.yml`.
- **`bootstrap.sh`**: one-liner to install ansible (brew or uv) and run target playbook.

## Cross-references

- Tech stack: `mem:tech_stack`
- Commands: `mem:suggested_commands`
- Conventions: `mem:conventions`
- Task completion: `mem:task_completion`
