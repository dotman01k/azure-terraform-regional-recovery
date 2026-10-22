# Forced regional recovery runbook

This procedure trades possible asynchronous data loss for recovery of a **verified fenced**
source. It refuses to promote if source-region ARM cannot prove the source stopped. Do not use
it as a total-region-unreachable automatic failover controller. Ensure the SQL operator can reach
the target over the private network and the controller account is available.

## Prepare and fence

Record incident ID, source/target resource IDs, observed lag, application consistency requirements,
writer discovery epoch and authorized decision maker. Stop other administrative changes. Use
`recover.yml` action `observe` first. Review evidence privately under `.run` on the runner.
Update `NETWORK_TFVARS_JSON` with `fence_primary=true` and leave it true throughout recovery.
Plan and apply the network stack. Its priority-100 deny TCP5432 rule must be attached to the exact
primary database subnet; rules of a higher priority invalidate the policy. NSGs are stateful, so
this alone does not kill established connections.

Run the protected stop action with the exact target ID from the manifest:

```bash
export REPO=dotman01k/azure-terraform-regional-recovery
export TARGET='/subscriptions/REAL_SUB/resourceGroups/rg-drpg-recovery/providers/Microsoft.DBforPostgreSQL/flexibleServers/REAL_REPLICA'
gh workflow run recover.yml --repo "$REPO" --ref main -f action=stop-primary -f confirm_target="$TARGET"
```

The controller checks fencing before stopping the source and checks actual stopped status
afterward. If it cannot prove either condition, stop. Never edit evidence or change the manifest
to impersonate the actual source. Azure can restart a stopped PostgreSQL server after its stop
window, so retain the attached persistent deny rule and track the old server until retirement.

## Authorize, promote and probe

```bash
gh workflow run recover.yml --repo "$REPO" --ref main -f action=authorize \
  -f incident=INC-20261022-001 -f confirm_target="$TARGET" -f ack_possible_data_loss=true
# Wait for success and review the journal, then:
gh workflow run recover.yml --repo "$REPO" --ref main -f action=promote -f confirm_target="$TARGET"
gh workflow run recover.yml --repo "$REPO" --ref main -f action=probe -f confirm_target="$TARGET"
```

Authorization is bound to a manifest hash, incident and epoch. Promotion requires fresh evidence
(maximum 15 minutes) before the actual promote request. Azure CLI uses forced standalone
promotion, creating an independent server; no reverse replication is assumed. If a request times
out, repeat the **same** promote action: it re-reads the actual role/source first and reconciles
an already promoted writer rather than blindly sending a second request. The source remains
fenced. The journal is a privileged operational artifact in the private `drcontrol` container.

The probe obtains an Entra token, passes it only via the child psql environment, uses the
canonical TLS hostname with `sslmode=verify-full`, creates/inserts inside a transaction and
rolls back. Both actual SQL writability and management-plane authentication configuration matter.
Ready status by itself is insufficient. A failed probe never authorizes routing.

## Transfer Terraform ownership

Freeze the original primary and replica roots. The journal causes their plans to be rejected.
Run the stage workflow, plan then apply, for `replica-detach`. It initializes the **old replica
key** and accepts only no-op/forget actions. Its removed block has `destroy=false`. Confirm
that the old state no longer contains either module resource. Do not delete the backend blob.

Next run plan then apply for `recovered`. It initializes a **new recovered key** and imports the
exact promoted server and its administrator. The gate accepts no cloud create/update/delete
or replacement during adoption. If Terraform proposes changes, compare actual server settings
with module inputs and creation-only provider fields, repair configuration and review again.
Do not disable the gate or run the original replica root to repair ownership.

```bash
gh workflow run terraform.yml --repo "$REPO" --ref main -f stack=replica-detach -f operation=plan
# Review, then same command with operation=apply. Wait for completion.
gh workflow run terraform.yml --repo "$REPO" --ref main -f stack=recovered -f operation=plan
# Review, then same command with operation=apply. Wait for completion.
gh workflow run recover.yml --repo "$REPO" --ref main -f action=adopted -f confirm_target="$TARGET"
```

Adopted verifies initialized backend keys/account/container, distinct lineages, empty old
ownership, exact two-resource new ownership and actual SQL writability. Preserve state versions
and the journal before proceeding. The temporary ownership gap is deliberate and serialized;
only the recovered root can own the promoted database afterward.

## Switch supported clients

Update `ROUTING_TFVARS_JSON` to target canonical hostname and epoch 2. Plan and apply the routing
stack with `confirm_target` set. Both operations acquire the campaign lease; immediately before
apply the controller refreshes source/fence, target, SQL and ownership evidence. The plan gate
requires an adopted journal and matching epoch. Existing client pools must refresh deliberately.

```bash
gh workflow run terraform.yml --repo "$REPO" --ref main -f stack=routing -f operation=plan -f confirm_target="$TARGET"
# Review, then repeat with operation=apply.
python -m recovery.discovery --manifest .run/manifest.json --minimum-epoch 2
```

Only clients implementing this TXT discovery contract participate. Use the returned canonical
hostname for TLS, never the discovery-zone name. Measure application recovery time, missing
sequence numbers and client retry behavior. Keep the old server fenced. See rebuild.md.

## Interrupted operations and lock recovery

An infinite campaign lease prevents concurrent compliant controllers. If a process crashes,
inspect GitHub runs, Terraform locks and all operator sessions before intervening. Only after
proving there is no active owner, an authorized storage operator may explicitly break the
campaign lease:

```bash
az storage blob lease break --account-name "$BACKEND_ACCOUNT" --container-name drcontrol \
  --blob-name campaign.lock --lease-break-period 0 --auth-mode login
```

Do not automatically break leases or force-unlock Terraform. If authorization expires before
promotion, preserve the existing journal/version, verify that promotion never occurred and the
old route is still primary, then have an incident administrator archive the abandoned journal
outside the active `incident.json` key and authorize again with fresh observations. This reset
is intentionally not automated. Never reset a promoted/adopted campaign to bypass its state.
For a partially completed handoff, inspect both state versions and resume the appropriate stage;
never restore a snapshot that introduces a second owner. A manifest hash mismatch requires
investigation and a reviewed new campaign, not editing the existing evidence in place.
