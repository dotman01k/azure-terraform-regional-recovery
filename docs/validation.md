# Validation evidence

Preparation date: 2026-10-22.

- 44 Python policy/controller tests passed locally, including stale evidence, missing fencing,
  unknown/duplicate writer ownership, explicit data-loss acknowledgement, reverse epochs,
  unsafe import plans, distributed lease handling and uncertain-promotion retry behavior.
- Terraform 1.13.0 fmt parsed all configuration and formatting checks passed.
- The pinned AzureRM 4.68.0 package was downloaded and provider lock files were generated.
- Actionlint v1.7.12 passed with the documented private-runner label configuration.
- Bash and Python source syntax were checked.

The preparation environment denied the Unix socket needed by the real AzureRM provider plugin.
Local provider-schema validation and Terraform mock plans therefore did NOT pass locally and
are not claimed as local successes. The hosted GitHub CI runs all roots' terraform validate and
11 mock-provider plan tests plus the Python suite, with no Azure credentials. Its independent
result is the authority for those checks. See the Actions tab for the published commit.

Not established by offline tests: Azure API acceptance, regional SKU/HA support, private DNS
reachability, Entra SQL authorization, replica lag, stop/fence enforcement against all application
paths, data-loss bounds, promotion timing, state adoption against real resources, or client pool
turnover. Record these in a real approved drill before using the design for production recovery.
No RPO/RTO guarantee is inferred from passing tests or Terraform configuration.
