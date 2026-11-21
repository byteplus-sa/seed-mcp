mock_provider "bytepluscc" {
  override_during = plan

  mock_resource "bytepluscc_vpc_vpc" {
    defaults = { vpc_id = "vpc-synthetic" }
  }
  mock_resource "bytepluscc_natgateway_ngw" {
    defaults = { nat_gateway_id = "ngw-synthetic" }
  }
  mock_resource "bytepluscc_vpc_eip" {
    defaults = { allocation_id = "eip-synthetic" }
  }
  mock_resource "bytepluscc_vke_cluster" {
    defaults = { cluster_id = "cluster-synthetic" }
  }
  mock_resource "bytepluscc_apig_gateway" {
    defaults = {
      gateway_id = "gateway-synthetic"
      log_spec = {
        enable     = false
        project_id = ""
        topic_id   = ""
      }
      trace_spec = { enable = false }
    }
  }
}

override_resource {
  override_during = plan
  target          = bytepluscc_vpc_subnet.private["nodes"]
  values          = { subnet_id = "subnet-nodes" }
}
override_resource {
  override_during = plan
  target          = bytepluscc_vpc_subnet.private["pods"]
  values          = { subnet_id = "subnet-pods" }
}
override_resource {
  override_during = plan
  target          = bytepluscc_vpc_subnet.private["edge"]
  values          = { subnet_id = "subnet-edge" }
}

variables {
  fresh_state_confirmed = true
  zone_id               = "ap-southeast-1a"
  # Synthetic source compatibility only, not regional VKE inventory.
  kubernetes_version = "1.37"
  node_instance_type = "ecs.g3i.xlarge"
}

run "private_shared_state_infrastructure" {
  command = plan

  assert {
    condition     = bytepluscc_vke_cluster.dedicated.delete_protection_enabled && !bytepluscc_vke_cluster.dedicated.cluster_config.api_server_public_access_enabled && !bytepluscc_vke_cluster.dedicated.cluster_config.resource_public_access_default_enabled
    error_message = "Cluster deletion protection and private-only API/nodes are mandatory."
  }
  assert {
    condition     = bytepluscc_vke_node_pool.application.auto_scaling.desired_replicas == 2 && !bytepluscc_vke_node_pool.application.auto_scaling.enabled && !bytepluscc_vke_node_pool.application.node_config.public_access_enabled && bytepluscc_vke_node_pool.application.node_config.instance_charge_type == "PostPaid" && bytepluscc_vke_node_pool.application.node_config.spot_strategy == "NoSpot"
    error_message = "The baseline must retain two fixed private on-demand nodes, never Spot."
  }
  assert {
    condition     = length(bytepluscc_vke_node_pool.burst) == 0 && output.burst_node_pool_id == null
    error_message = "Burst scaling must be opt-in and absent by default."
  }
  assert {
    condition     = bytepluscc_natgateway_ngw.egress.network_type == "internet" && bytepluscc_vpc_eip.egress.instance_type == "Nat" && bytepluscc_vpc_eip.egress.instance_id == bytepluscc_natgateway_ngw.egress.nat_gateway_id
    error_message = "Public NAT must have an explicitly bound EIP."
  }
  assert {
    condition     = length(bytepluscc_natgateway_snatentry.private) == 2 && alltrue([for name, snat in bytepluscc_natgateway_snatentry.private : snat.subnet_id == bytepluscc_vpc_subnet.private[name].subnet_id && snat.eip_id == bytepluscc_vpc_eip.egress.allocation_id])
    error_message = "Both private node and VPC-CNI pod subnets need SNAT."
  }
  assert {
    condition     = bytepluscc_vpc_route_table.private_egress.subnet_ids == toset(["subnet-nodes", "subnet-pods"]) && one(bytepluscc_vpc_route_table.private_egress.custom_route_entries).next_hop_type == "NatGW" && one(bytepluscc_vpc_route_table.private_egress.custom_route_entries).next_hop_id == bytepluscc_natgateway_ngw.egress.nat_gateway_id && one(bytepluscc_vpc_route_table.private_egress.custom_route_entries).destination_cidr_block == "0.0.0.0/0"
    error_message = "Node/pod routes must use NAT explicitly; the NAT/CLB subnet must not route back to itself."
  }
  assert {
    condition     = alltrue([for subnet in bytepluscc_vpc_subnet.private : subnet.zone_id == var.zone_id]) && length(toset([for subnet in bytepluscc_vpc_subnet.private : subnet.cidr_block])) == 3
    error_message = "Private subnets must be distinct and in the selected node zone."
  }
  assert {
    condition     = !output.helm_infrastructure_values.prerequisitesConfirmed && output.helm_infrastructure_values.service.subnetId == "subnet-edge" && toset(keys(output.helm_infrastructure_values)) == toset(["prerequisitesConfirmed", "service"])
    error_message = "Safe outputs must not acknowledge administrator-owned readiness or couple application pods to storage."
  }
}

run "private_bounded_burst_pool" {
  command = plan
  variables { burst_node_max_count = 2 }
  assert {
    condition     = length(bytepluscc_vke_node_pool.burst) == 1 && bytepluscc_vke_node_pool.burst[0].auto_scaling.enabled && bytepluscc_vke_node_pool.burst[0].auto_scaling.desired_replicas == 0 && bytepluscc_vke_node_pool.burst[0].auto_scaling.min_replicas == 0 && bytepluscc_vke_node_pool.burst[0].auto_scaling.max_replicas == 2 && bytepluscc_vke_node_pool.burst[0].auto_scaling.subnet_policy == "ZoneBalance"
    error_message = "The separate burst pool starts empty and permits only 0-2 additional nodes."
  }
  assert {
    condition     = bytepluscc_vke_node_pool.application.auto_scaling.desired_replicas == 2 && !bytepluscc_vke_node_pool.application.auto_scaling.enabled
    error_message = "Enabling burst nodes must not alter fixed baseline ownership."
  }
  assert {
    condition     = bytepluscc_vke_node_pool.burst[0].node_config.instance_type_ids == bytepluscc_vke_node_pool.application.node_config.instance_type_ids && bytepluscc_vke_node_pool.burst[0].node_config.subnet_ids == bytepluscc_vke_node_pool.application.node_config.subnet_ids && bytepluscc_vke_node_pool.burst[0].node_config.project_name == var.project_name && local.worker_node_config.security.login == null && !bytepluscc_vke_node_pool.burst[0].node_config.public_access_enabled && bytepluscc_vke_node_pool.burst[0].node_config.instance_charge_type == "PostPaid" && bytepluscc_vke_node_pool.burst[0].node_config.spot_strategy == "NoSpot" && bytepluscc_vke_node_pool.burst[0].node_config.system_volume.size == 80 && bytepluscc_vke_node_pool.burst[0].node_config.system_volume.type == "ESSD_PL0"
    error_message = "Burst nodes must use identical private on-demand configuration, not Spot or public IPs."
  }
}

run "gateway_disabled_by_default" {
  command = plan
  assert {
    condition     = length(bytepluscc_apig_gateway.public) == 0 && length(bytepluscc_vpc_subnet.private) == 3 && output.public_gateway_id == null
    error_message = "APIG and additional subnets must be absent without explicit enablement."
  }
}

run "dedicated_two_zone_gateway" {
  command = plan
  variables {
    public_gateway_enabled    = true
    gateway_secondary_zone_id = "ap-southeast-1b"
    burst_node_max_count      = 2
  }
  override_resource {
    target          = bytepluscc_vpc_subnet.private["gateway-primary"]
    override_during = plan
    values          = { subnet_id = "subnet-gateway-primary" }
  }
  override_resource {
    target          = bytepluscc_vpc_subnet.private["gateway-secondary"]
    override_during = plan
    values          = { subnet_id = "subnet-gateway-secondary" }
  }
  assert {
    condition     = bytepluscc_apig_gateway.public[0].name == "${var.name}-gateway" && bytepluscc_apig_gateway.public[0].project_name == var.project_name && bytepluscc_apig_gateway.public[0].vpc_id == bytepluscc_vpc_vpc.dedicated.vpc_id && bytepluscc_apig_gateway.public[0].type == "standard"
    error_message = "The gateway must be new and dedicated to the selected VPC/project."
  }
  assert {
    condition     = bytepluscc_apig_gateway.public[0].subnet_ids == toset([bytepluscc_vpc_subnet.private["gateway-primary"].subnet_id, bytepluscc_vpc_subnet.private["gateway-secondary"].subnet_id]) && bytepluscc_vpc_subnet.private["gateway-primary"].zone_id == var.zone_id && bytepluscc_vpc_subnet.private["gateway-secondary"].zone_id == var.gateway_secondary_zone_id && length(toset([for subnet in bytepluscc_vpc_subnet.private : subnet.cidr_block])) == 5 && bytepluscc_vpc_subnet.private["gateway-primary"].cidr_block == "10.80.48.0/20" && bytepluscc_vpc_subnet.private["gateway-secondary"].cidr_block == "10.80.64.0/20"
    error_message = "Gateway subnets must occupy distinct AZs and distinct derived /20 ranges."
  }
  assert {
    condition     = bytepluscc_apig_gateway.public[0].resource_spec.instance_spec_code == "1c2g" && bytepluscc_apig_gateway.public[0].resource_spec.replicas == 2 && bytepluscc_apig_gateway.public[0].resource_spec.clb_spec_code == "small_1" && bytepluscc_apig_gateway.public[0].resource_spec.public_network_billing_type == "traffic" && bytepluscc_apig_gateway.public[0].resource_spec.network_type.enable_private_network && bytepluscc_apig_gateway.public[0].resource_spec.network_type.enable_public_network
    error_message = "Gateway resources must match the explicit two-node traffic-billed configuration."
  }
  assert {
    condition     = !bytepluscc_apig_gateway.public[0].log_spec.enable && !bytepluscc_apig_gateway.public[0].monitor_spec.enable && !bytepluscc_apig_gateway.public[0].trace_spec.enable && !output.helm_infrastructure_values.prerequisitesConfirmed
    error_message = "Gateway logging/tracing must be off and infrastructure must not imply delivery readiness."
  }
  assert {
    condition     = !bytepluscc_vke_cluster.dedicated.cluster_config.api_server_public_access_enabled && !bytepluscc_vke_cluster.dedicated.cluster_config.resource_public_access_default_enabled && !bytepluscc_vke_node_pool.application.node_config.public_access_enabled && !bytepluscc_vke_node_pool.application.auto_scaling.enabled && bytepluscc_vke_node_pool.application.auto_scaling.desired_replicas == 2 && bytepluscc_vke_node_pool.burst[0].auto_scaling.desired_replicas == 0 && bytepluscc_vke_node_pool.burst[0].auto_scaling.max_replicas == 2
    error_message = "Public APIG must not expose the Kubernetes API/nodes or change worker ownership."
  }
  assert {
    condition     = length(bytepluscc_natgateway_snatentry.private) == 2 && bytepluscc_vpc_route_table.private_egress.subnet_ids == toset(["subnet-nodes", "subnet-pods"]) && bytepluscc_vpc_subnet.private["nodes"].cidr_block == "10.80.0.0/20" && bytepluscc_vpc_subnet.private["pods"].cidr_block == "10.80.16.0/20" && bytepluscc_vpc_subnet.private["edge"].cidr_block == "10.80.32.0/20"
    error_message = "Gateway preparation must preserve node/pod egress and existing subnet ranges."
  }
}

run "reject_enabled_gateway_without_secondary_zone" {
  command = plan
  variables { public_gateway_enabled = true }
  expect_failures = [var.gateway_secondary_zone_id]
}

run "reject_same_gateway_zone" {
  command = plan
  variables {
    public_gateway_enabled    = true
    gateway_secondary_zone_id = "ap-southeast-1a"
  }
  expect_failures = [var.gateway_secondary_zone_id]
}

run "reject_wrong_region_gateway_zone" {
  command = plan
  variables {
    public_gateway_enabled    = true
    gateway_secondary_zone_id = "cn-beijing-a"
  }
  expect_failures = [var.gateway_secondary_zone_id]
}

run "reject_ignored_gateway_zone" {
  command = plan
  variables { gateway_secondary_zone_id = "ap-southeast-1b" }
  expect_failures = [var.gateway_secondary_zone_id]
}

run "reject_logging_readback_enabled" {
  command = plan
  variables {
    public_gateway_enabled    = true
    gateway_secondary_zone_id = "ap-southeast-1b"
  }
  override_resource {
    target          = bytepluscc_apig_gateway.public[0]
    override_during = plan
    values = {
      log_spec = {
        enable     = true
        project_id = "synthetic"
        topic_id   = "synthetic"
      }
    }
  }
  expect_failures = [bytepluscc_apig_gateway.public[0]]
}

run "logging_guard_null_semantics" {
  command = plan
  variables { public_gateway_enabled = false }
  # The mock engine rejects null log_spec before evaluating a postcondition.
  # Source tests pin the production expression; these assert its null semantics.
  assert {
    condition     = !try((var.public_gateway_enabled ? { enable = false } : null).enable == false, false) && !try(({ enable = var.public_gateway_enabled ? false : null }).enable == false, false)
    error_message = "Missing logging objects and null enable flags must not establish disabled logging."
  }
}

run "reject_tracing_readback_enabled" {
  command = plan
  variables {
    public_gateway_enabled    = true
    gateway_secondary_zone_id = "ap-southeast-1b"
  }
  override_resource {
    target          = bytepluscc_apig_gateway.public[0]
    override_during = plan
    values          = { trace_spec = { enable = true } }
  }
  expect_failures = [bytepluscc_apig_gateway.public[0]]
}

run "reject_negative_burst_nodes" {
  command = plan
  variables { burst_node_max_count = -1 }
  expect_failures = [var.burst_node_max_count]
}

run "reject_fractional_burst_nodes" {
  command = plan
  variables { burst_node_max_count = 1.5 }
  expect_failures = [var.burst_node_max_count]
}

run "reject_unbounded_burst_nodes" {
  command = plan
  variables { burst_node_max_count = 9 }
  expect_failures = [var.burst_node_max_count]
}

run "reject_combined_node_limit" {
  command = plan
  variables {
    node_count           = 9
    burst_node_max_count = 2
  }
  expect_failures = [var.burst_node_max_count]
}

run "reject_unacknowledged_state" {
  command = plan
  variables { fresh_state_confirmed = false }
  expect_failures = [var.fresh_state_confirmed]
}

run "reject_public_vpc" {
  command = plan
  variables { vpc_cidr = "8.8.0.0/16" }
  expect_failures = [var.vpc_cidr]
}

run "reject_malformed_vpc" {
  command = plan
  variables { vpc_cidr = "not-a-cidr" }
  expect_failures = [var.vpc_cidr]
}

run "reject_overlapping_services" {
  command = plan
  variables { service_cidr = "10.80.0.0/16" }
  expect_failures = [var.service_cidr]
}

run "reject_public_services" {
  command = plan
  variables { service_cidr = "8.8.0.0/16" }
  expect_failures = [var.service_cidr]
}

run "reject_zero_nodes" {
  command = plan
  variables { node_count = 0 }
  expect_failures = [var.node_count]
}

run "reject_fractional_nodes" {
  command = plan
  variables { node_count = 2.5 }
  expect_failures = [var.node_count]
}

run "reject_wrong_region_zone" {
  command = plan
  variables { zone_id = "cn-beijing-a" }
  expect_failures = [var.zone_id]
}

run "reject_unverified_version" {
  command = plan
  variables { kubernetes_version = "" }
  expect_failures = [var.kubernetes_version]
}

run "reject_kubernetes_1_27" {
  command = plan
  variables { kubernetes_version = "1.27" }
  expect_failures = [var.kubernetes_version]
}

run "reject_kubernetes_1_28" {
  command = plan
  variables { kubernetes_version = "1.28" }
  expect_failures = [var.kubernetes_version]
}

run "reject_kubernetes_1_29" {
  command = plan
  variables { kubernetes_version = "1.29" }
  expect_failures = [var.kubernetes_version]
}

run "accept_kubernetes_compatibility_floor_only" {
  command = plan
  variables { kubernetes_version = "1.30" }
  assert {
    condition     = bytepluscc_vke_cluster.dedicated.kubernetes_version_create == "1.30"
    error_message = "The source compatibility floor is 1.30; this mock does not prove maintenance or regional availability."
  }
}

run "reject_kubernetes_patch_input" {
  command = plan
  variables { kubernetes_version = "1.37.2" }
  expect_failures = [var.kubernetes_version]
}

run "reject_empty_node_type" {
  command = plan
  variables { node_instance_type = "" }
  expect_failures = [var.node_instance_type]
}

run "reject_unbounded_egress" {
  command = plan
  variables { nat_bandwidth_mbps = 201 }
  expect_failures = [var.nat_bandwidth_mbps]
}

run "reject_noncanonical_network" {
  command = plan
  variables { vpc_cidr = "10.080.0.0/16" }
  expect_failures = [var.vpc_cidr]
}

run "reject_noncanonical_overlapping_service_network" {
  command = plan
  variables { service_cidr = "10.080.0.0/16" }
  expect_failures = [var.service_cidr]
}

run "reject_region_prefix_collision" {
  command = plan
  variables { zone_id = "ap-southeast-11a" }
  expect_failures = [var.zone_id]
}

run "custom_private_network_and_existing_key_name" {
  command = plan
  variables {
    vpc_cidr                   = "172.16.0.0/16"
    service_cidr               = "192.168.0.0/16"
    existing_ssh_key_pair_name = "synthetic-existing-key"
    node_count                 = 3
  }
  assert {
    condition     = bytepluscc_vpc_subnet.private["pods"].cidr_block == "172.16.16.0/20" && bytepluscc_vke_node_pool.application.node_config.security.login.ssh_key_pair_name == "synthetic-existing-key" && bytepluscc_vke_node_pool.application.auto_scaling.desired_replicas == 3
    error_message = "Custom inputs must retain derived private networking and accept only an existing key name."
  }
}
