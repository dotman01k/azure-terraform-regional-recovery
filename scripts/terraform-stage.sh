#!/usr/bin/env bash
# Live Terraform operations; manual protected workflow only.
set -euo pipefail
cd "$(dirname "$0")/.."
stack="${1:?Choose stack}"
operation="${2:-plan}"
case "$stack" in network|primary|replica|routing|replica-detach|recovered) ;; *) exit 2 ;; esac
[[ "$operation" == plan || "$operation" == apply ]] || exit 2
: "${BACKEND_ACCOUNT:?Set backend account}"
: "${BACKEND_RESOURCE_GROUP:?Set backend resource group}"
: "${TFVARS_JSON:?Set JSON variables for this stack}"
: "${RECOVERY_MANIFEST_JSON:?Set the reviewed manifest JSON}"
mkdir -p .run
umask 077
python - "$stack" <<'PY'
import json,os,sys
from pathlib import Path
from recovery.policy import validate_manifest,topology
values=json.loads(os.environ['TFVARS_JSON'])
m=validate_manifest(json.loads(os.environ['RECOVERY_MANIFEST_JSON']))
assert m['control']['account']==os.environ['BACKEND_ACCOUNT'],'Manifest/backend account mismatch'
if sys.argv[1]=='network' and 'regions' in values:topology(values['regions'])
Path('.run/variables.tfvars.json').write_text(json.dumps(values))
Path('.run/manifest.json').write_text(json.dumps(m))
PY
# Backend keys are code-owned. replica-detach MUST use the old replica key.
key="$stack"
[[ "$stack" == replica-detach ]] && key=replica
terraform -chdir="stacks/$stack" init -input=false -reconfigure -lockfile=readonly \
  -backend-config="resource_group_name=$BACKEND_RESOURCE_GROUP" \
  -backend-config="storage_account_name=$BACKEND_ACCOUNT" \
  -backend-config=container_name=tfstate \
  -backend-config="key=regional-recovery/$key.tfstate" \
  -backend-config=use_azuread_auth=true -backend-config=use_oidc=true > .run/init.log
# Fresh source-stop, NSG, SQL and state ownership evidence is mandatory for a recovery route.
gateargs=()
[[ -f .run/journal.json ]] && gateargs+=(--journal .run/journal.json)
if [[ "$stack" == routing ]]; then
  recovery_route=$(python -c "import json;v=json.load(open('.run/variables.tfvars.json'));m=json.load(open('.run/manifest.json'));print(str(v['writer_fqdn']==m['target']['fqdn']).lower())")
  if [[ "$recovery_route" == true ]]; then
    : "${CONFIRM_TARGET:?Exact recovery target required}"
    # State adoption check needs both backends initialized in this checkout.
    bash scripts/init-recovery-states.sh
    python -m recovery.live routing-evidence --manifest .run/manifest.json --output .run/journal.json \
      --execute --confirm-target "$CONFIRM_TARGET"
    gateargs=(--journal .run/journal.json)
  fi
fi
terraform -chdir="stacks/$stack" plan -input=false -lock-timeout=120s \
  -var-file=../../.run/variables.tfvars.json -out=../../.run/approved.tfplan > .run/plan.log
terraform -chdir="stacks/$stack" show -json ../../.run/approved.tfplan > .run/plan.json
python -m recovery.gate --stack "$stack" --plan .run/plan.json --manifest .run/manifest.json "${gateargs[@]}"
if [[ "$operation" == apply ]]; then
  [[ "${CONFIRM_STACK:-}" == "$stack" ]] || { echo 'Set CONFIRM_STACK to the exact stack name' >&2; exit 2; }
  # Re-check the routing fence after planning; never rely only on a cached observation.
  if [[ "$stack" == routing && "${recovery_route:-false}" == true ]]; then
    python -m recovery.live routing-evidence --manifest .run/manifest.json --output .run/journal.json \
      --execute --confirm-target "$CONFIRM_TARGET"
    python -m recovery.gate --stack "$stack" --plan .run/plan.json --manifest .run/manifest.json --journal .run/journal.json
  fi
  terraform -chdir="stacks/$stack" apply -input=false ../../.run/approved.tfplan > .run/apply.log
  echo "Applied the gated saved plan. Private logs remain under .run/."
fi
