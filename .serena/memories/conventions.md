# Ansible Playbooks — Conventions

## Playbook Style
- **One concern per playbook**: `base.yml` = generic tools, `work.yml` = Jeff profile + services, `serena.yml` = serena config.
- **No become**: `become: false` is explicit in every playbook.
- **`changed_when: false`** for read-only commands (`brew --version`, `serena --version`).
- **`failed_when: false`** for cleanup handlers (launchctl bootout may fail if not loaded).
- **OS gating**: `when: ansible_facts['os_family'] == 'Darwin'` for macOS-only tasks.

## Variable Naming
- **snake_case**: all variable names (ansible convention).
- **Group vars by OS**: `all.yml` (universal), `macbooks.yml` (macOS), `linux.yml` (Linux), `workstations.yml` (shared).
- **Host vars**: one file per host (`jeff-macbook.yml`, `betsy.yml`).
- **Secrets**: `secrets.yml` (gitignored) for tokens/keys.

## Template Conventions
- **`.j2` extension** on all templates.
- **`validate` parameter** on plist templates (`plutil -lint %s`).
- **Absolute paths from playbook_dir**: `{{ playbook_dir }}/../roles/...` for template sources.

## Inventory
- **Host groups**: `[macbooks]`, `[linux]`, `[workstations:children]`.
- **Local connection**: `ansible_connection=local` for the primary work machine.
- **Linux hosts**: commented-out scaffold with `ansible_host` placeholder.

## Companion Python (`serena-bulk-index.py`)
- **stdlib-first**: PyYAML is the only non-stdlib dependency.
- **Defensive**: every LSP runtime is checked before being passed to serena.
- **Fail-safe**: projects that fail indexing are removed from config and added to pending.
- **Idempotent**: can be re-run; already-indexed projects are skipped.
