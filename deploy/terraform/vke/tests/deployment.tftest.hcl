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
    error_message = "Use two fixed private on-demand nodes; never spot or node autoscaling."
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
