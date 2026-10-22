#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
python -m unittest discover -s tests -v
for file in scripts/*.sh; do bash -n "$file"; done
terraform fmt -check -recursive
for root in modules/database stacks/network stacks/primary stacks/replica stacks/routing stacks/replica-detach stacks/recovered; do
  terraform -chdir="$root" init -backend=false -input=false -lockfile=readonly >/dev/null
  terraform -chdir="$root" validate -no-color
  if [[ -d "$root/tests" ]]; then terraform -chdir="$root" test -no-color; fi
done
