# Ansible Playbooks — Task Completion

After modifying playbooks, roles, or templates, run in order:

```bash
# 1. Syntax check all playbooks
ansible-playbook playbooks/base.yml --syntax-check
ansible-playbook playbooks/work.yml --syntax-check
ansible-playbook playbooks/serena.yml --syntax-check
ansible-playbook playbooks/drift.yml --syntax-check
ansible-playbook playbooks/pi.yml --syntax-check
ansible-playbook playbooks/omp.yml --syntax-check
ansible-playbook playbooks/cursor.yml --syntax-check

# 2. Lint all
ansible-lint playbooks/ roles/

# 3. Drift check (dry-run, no changes)
ansible-playbook playbooks/drift.yml --check --diff
```

After modifying `serena-bulk-index.py`:

```bash
python3 serena-bulk-index.py --test    # run unit tests
```
