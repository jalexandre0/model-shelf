# Ansible Playbooks — Suggested Commands

## Bootstrap (first run on a fresh machine)
```bash
./bootstrap.sh base     # install ansible + run base playbook
./bootstrap.sh work     # run full work profile
```

## Playbook Execution
```bash
ansible-playbook playbooks/base.yml                    # generic dev machine
ansible-playbook playbooks/work.yml                    # full Jeff work profile
ansible-playbook playbooks/serena.yml                  # regenerate serena global config
ansible-playbook playbooks/pi.yml                      # Pi config (scaffold)
ansible-playbook playbooks/omp.yml                     # OMP config (scaffold)
ansible-playbook playbooks/cursor.yml                  # Cursor IDE config (scaffold)
```

## Drift Detection
```bash
ansible-playbook playbooks/drift.yml --check --diff    # detect configuration drift
```

## Lint & Syntax Check
```bash
ansible-lint playbooks/ roles/                         # lint all
ansible-playbook playbooks/base.yml --syntax-check
ansible-playbook playbooks/work.yml --syntax-check
ansible-playbook playbooks/drift.yml --syntax-check
```

## Serena Bulk Index
```bash
python3 serena-bulk-index.py                           # batch index all projects
python3 serena-bulk-index.py --test                    # run unit tests
```

## Git
```bash
git diff --stat                                        # standard git (macOS/Darwin)
```
