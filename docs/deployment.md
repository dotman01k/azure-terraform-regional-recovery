# Deployment and identity runbook

## 1. Review scope before creating infrastructure

Use a disposable subscription with General Purpose PostgreSQL capacity in East US and West US 3.
Verify PostgreSQL 16, `GP_Standard_D2s_v3`, zone-redundant HA, geo-backups and cross-region replica
support for your offer. Quota and regional capacity must be checked live. The examples are
contracts, not a ready-to-use subscription configuration. Expected steady-state capacity is an
HA primary plus one asynchronous replica. Budget for compute, storage, backups and transfer.

Install Terraform 1.13.0, Python 3.12, Azure CLI, Bash, psql, trusted CA roots and dig. Run
`bash scripts/validate.sh` before any live change. The project does not install these tools
on a private runner or create a billable runner for you.

## 2. Bootstrap dedicated groups and remote storage

An administrator creates `rg-drpg-primary` in `eastus` and `rg-drpg-recovery` in `westus3`.
Network state reads these existing groups. Register Microsoft.Network, Microsoft.DBforPostgreSQL
and Microsoft.Storage before using the deployment identity. Use an existing dedicated backend
account in the recovery region with an organization-approved redundancy tier. Require TLS 1.2,
disable shared-key access, prohibit public blob access, restrict network access to trusted
operators, and enable blob versioning and soft delete. Account firewalls/private endpoints
must permit the operator runner. The account is a recovery dependency and is not owned by
any of the six Terraform roots.

Create private containers `tfstate` and `drcontrol`. With an administrator signed in using
Entra data-plane permissions, initialize the campaign lock **once**, on a controlled machine:

```bash
export BACKEND_ACCOUNT=YOUR_UNIQUE_ACCOUNT
az storage container create --account-name "$BACKEND_ACCOUNT" --name tfstate --auth-mode login
az storage container create --account-name "$BACKEND_ACCOUNT" --name drcontrol --auth-mode login
printf '%s\n' 'regional-recovery-lock-v1' > campaign.lock
az storage blob upload --account-name "$BACKEND_ACCOUNT" --container-name drcontrol \
  --name campaign.lock --file campaign.lock --overwrite false --auth-mode login
rm campaign.lock
```

Never overwrite, delete or recreate this blob to clear a lock. The controller takes an infinite
lease on it. Each Terraform state additionally uses its own backend lease. These serve different
purposes: one serializes the entire recovery campaign, the other protects one state transaction.

## 3. Configure identities and runner

Create an Entra security group for PostgreSQL administration and set its object ID, display name
and tenant ID in the database inputs. The SQL-probe identity must be a tested member with database
access; test short-lived Entra-token login while the primary is healthy. The deployment identity
has Contributor on both project RGs. It needs Storage Blob Data Contributor on both backend
containers. Do not grant tenant directory administration or Owner to the deployment workflow.
Grant group membership and provider registration using separate bootstrap privileges.

Use a dedicated Linux self-hosted GitHub runner labelled `dr-operator`, with private connectivity
to the reserved client subnets in both VNets and access to Azure/GitHub identity and control-plane
endpoints. Arrange connectivity before deployment; the network root does not connect your laptop.
Never run untrusted pull requests on this runner. Restrict runner administration and clear private
`.run` files after retaining evidence securely. Use a single trusted deployment/recovery identity
for this lab; separate operational roles are a production extension.

Create GitHub environment `dr-control`, restrict deployments to `main`, and configure required
reviewers. In Entra, add GitHub OIDC federation for **this repository and environment** with audience
`api://AzureADTokenExchange` and issuer `https://token.actions.githubusercontent.com`. Configure
the exact subject produced by your repository's OIDC subject template; do not assume a legacy
subject if your organization uses immutable IDs or a custom template. Observe claims in an
administrator-controlled diagnostic run if necessary, without logging bearer tokens. No client
secret is used. Set these environment variables in GitHub (not secret token values):

| Variable | Value |
| --- | --- |
| AZURE_CLIENT_ID | Federated application or managed identity client ID |
| AZURE_TENANT_ID | Entra tenant ID |
| AZURE_SUBSCRIPTION_ID | Sandbox subscription ID |
| BACKEND_ACCOUNT | Existing storage account name |
| BACKEND_RESOURCE_GROUP | Backend account RG |
| PG_ADMIN_GROUP | Exact PostgreSQL Entra admin group display name for psql |
| RECOVERY_MANIFEST_JSON | Reviewed manifest based on examples/manifest.json |
| NETWORK_TFVARS_JSON | Adapted examples/network.tfvars.json |
| PRIMARY_TFVARS_JSON | Adapted examples/primary.tfvars.json |
| REPLICA_TFVARS_JSON | Adapted examples/replica.tfvars.json |
| REPLICA_DETACH_TFVARS_JSON | Adapted examples/replica-detach.tfvars.json |
| RECOVERED_TFVARS_JSON | Adapted examples/recovered.tfvars.json |
| ROUTING_TFVARS_JSON | Adapted examples/routing.tfvars.json |

Use actual globally unique server names. Keep manifest IDs, group names, network output IDs and
all stack inputs consistent. Examples contain synthetic IDs. Inspect outputs with
`terraform -chdir=stacks/network output -json` in an authorized initialized checkout; do not
publish state or output files. No `terraform_remote_state` reader is granted broad state access.

## 4. Execute normal stages

From an authenticated GitHub CLI session, invoke the protected workflow separately for plan
and apply. Replace STACK with `network`, then `primary`, then `replica`, then `routing`:

```bash
gh workflow run terraform.yml --repo dotman01k/azure-terraform-regional-recovery \
  --ref main -f stack=STACK -f operation=plan
gh run list --repo dotman01k/azure-terraform-regional-recovery --workflow terraform.yml
# Review the private runner's .run/plan.log and approved plan before applying.
gh workflow run terraform.yml --repo dotman01k/azure-terraform-regional-recovery \
  --ref main -f stack=STACK -f operation=apply
```

Each apply creates and gates a fresh saved plan in the approved run, then applies that exact
plan. A previous plan run is not applied in a later run. Recheck configuration between approvals.
Remote keys are fixed under `regional-recovery/`; replica-detach uses `replica.tfstate`, recovered
uses `recovered.tfstate`. Never manually change the backend mapping to get a plan to pass.

Keep `fence_primary=false` initially. Set initial writer to the primary canonical hostname,
epoch 1. Verify private DNS resolution and Entra SQL login from each client network. Create a
small application test table and continuously record sequence numbers/time to measure actual
replication lag and data loss during a drill. The rollback-only controller probe is a writability
check and does not measure RPO. Confirm backups and operational alerts independently.

## 5. Stop conditions

Do not proceed if any hosted source validation fails, plan gate rejects a change, private
connectivity is missing, the SQL identity has not been tested, a state is unexpectedly populated,
or source/target IDs differ between evidence and configuration. Live plans must be reviewed;
mock-provider success cannot establish service acceptance. Import-only adoption may expose
provider defaults differing from an actual promoted server: reconcile configuration deliberately.
