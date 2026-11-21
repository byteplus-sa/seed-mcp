# Infrastructure preparation only; routing gates are in plans/PLAN_GATEWAY_DEPLOYMENT.md.
resource "bytepluscc_apig_gateway" "public" {
  count = var.public_gateway_enabled ? 1 : 0

  name         = "${var.name}-gateway"
  project_name = var.project_name
  type         = "standard"
  vpc_id       = bytepluscc_vpc_vpc.dedicated.vpc_id
  subnet_ids = [
    bytepluscc_vpc_subnet.private["gateway-primary"].subnet_id,
    bytepluscc_vpc_subnet.private["gateway-secondary"].subnet_id,
  ]
  resource_spec = {
    instance_spec_code = "1c2g"
    replicas           = 2
    clb_spec_code      = "small_1"
    network_type = {
      enable_private_network = true
      enable_public_network  = true
    }
    public_network_billing_type = "traffic"
  }
  # 0.0.63 requires a real topic for log_spec even when disabled. Never invent one.
  # No routes are created; disabled access logging must be established by readback.
  monitor_spec = { enable = false }
  # Partial disabled TraceSpec is rejected by native APIG. Leave tracing unset.

  lifecycle {
    postcondition {
      condition     = try(self.log_spec.enable == false, false)
      error_message = "Gateway access logging must read back disabled before any routes or BYOK traffic. Inspect the gateway; do not retry creation automatically."
    }
    postcondition {
      condition     = try(self.trace_spec.enable == false, false)
      error_message = "Gateway tracing must read back disabled before any routes or BYOK traffic. Inspect the gateway; do not retry creation automatically."
    }
  }
}
