# IMPORTANT: initialize this root with the ORIGINAL replica state key.
# This forgets Terraform ownership; it never deletes the Azure objects.
removed {
  from = module.replica
  lifecycle { destroy = false }
}
