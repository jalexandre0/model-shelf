# Ansible Playbooks — Tech Stack

## Configuration Management
- **Ansible** (core): playbook/role/template engine, no Ansible Tower/AWX
- **ansible-lint**: linting for playbooks and roles

## Package Managers (runtime dependencies)
- **brew** (macOS): user-mode package installation
- **apt** (Linux): system package installation  
- **pipx**: Python CLI tool isolation (ansible-lint injection)
- **uv**: Python package/tool installer (fallback for ansible)

## Templating & Config
- **Jinja2**: `.j2` templates for all config files (serena_config.yml, launchd plists, MCP configs)
- **launchd** (macOS): user agents at `~/Library/LaunchAgents/`
- **systemd** (Linux): user units at `~/.config/systemd/user/` (scaffold)

## Companion Python
- **Python 3.13+**: `serena-bulk-index.py` uses stdlib + PyYAML
- **PyYAML**: serena_config.yml parsing

## Version Pins
- No strict version pins. Ansible core is whatever brew/uv provides.
- Python: 3.13+ expected on work profile.
