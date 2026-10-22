#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${BACKEND_ACCOUNT:?}"
: "${BACKEND_RESOURCE_GROUP:?}"
for root in replica-detach recovered; do
  key="$root"
  [[ "$root" == replica-detach ]] && key=replica
  terraform -chdir="stacks/$root" init -input=false -reconfigure -lockfile=readonly \
    -backend-config="resource_group_name=$BACKEND_RESOURCE_GROUP" \
    -backend-config="storage_account_name=$BACKEND_ACCOUNT" \
    -backend-config=container_name=tfstate -backend-config="key=regional-recovery/$key.tfstate" \
    -backend-config=use_azuread_auth=true -backend-config=use_oidc=true > /dev/null
done
