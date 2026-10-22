# Rebuild, failback and retirement

Standalone promotion disconnects replication. The old primary is stale and must remain fenced.
Neither a healthy Azure status nor the end of an incident makes it safe to reverse the writer
route. Application writes after promotion exist only on the recovered writer until another
replica/backup strategy is established.

## Rebuild a protected topology

1. Inventory current ownership from both Azure and all backend states. Keep the recovered
   database owned only by recovered state. Preserve journals and blob versions.
2. Back up/export required data from the active writer using approved PostgreSQL tooling.
   Validate restore and application consistency in an isolated environment.
3. Design a new replica from the recovered writer in a distinct reviewed root/backend and
   unique server name. Re-evaluate region capacity, networking, DNS, Entra permissions, HA and
   asynchronous replication costs. This project intentionally does not automatically create
   reverse replication or re-use the old primary's stale disks.
4. Validate real replica catch-up, SQL access, backups and operations. Establish a fresh recovery
   manifest/campaign under change control; preserve the old campaign rather than overwriting it.
5. If business policy requires returning to the original region, use a separately designed
   planned switchover with supported Azure prerequisites, application write quiescence and
   observed lag. The forced standalone flow in this repository is not that switchover flow.
6. Retire the stale old primary only after reviewing retention and reconciliation needs.

## Explicit teardown

Normal plan policy rejects deletes/replacements and the database module has prevent_destroy.
Teardown therefore requires an explicit reviewed maintenance change; ordinary recovery workflows
cannot perform it. Disable client writes, retain necessary backups/exports, and reconcile the
single current state owner of each database before modifying lifecycle policy. Use scoped
Terraform plans from those owners. Remove replicas before their primary. Remove writer discovery,
servers/admin resources, DNS links, peering, subnet associations, subnets, NSGs and VNets in
reverse dependency order. Shared private DNS must outlive the servers using it.

Do not run the original replica root after forget or import the recovered server into two states.
If dedicated RG deletion is chosen instead of managed teardown, first prove the groups contain
only this project and preserve the corresponding states; Azure deletion leaves stale Terraform
ownership that must be reconciled explicitly. Do not delete shared backend/control storage as
part of an RG shortcut. Keep journals and state versions for the required retention period, then
remove project-specific blobs, OIDC federation, identity role assignments and runner access.

Record the final Azure inventory and resulting state inventory as cleanup evidence. An empty
Terraform output alone is not proof that no billable Azure resources remain.
