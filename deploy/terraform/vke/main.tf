locals {
  subnet_cidrs = {
    nodes = cidrsubnet(var.vpc_cidr, 4, 0)
    pods  = cidrsubnet(var.vpc_cidr, 4, 1)
    edge  = cidrsubnet(var.vpc_cidr, 4, 2)
  }
  egress_subnets = {
    nodes = bytepluscc_vpc_subnet.private["nodes"].subnet_id
    pods  = bytepluscc_vpc_subnet.private["pods"].subnet_id
  }
  worker_node_config = {
    instance_type_ids     = [var.node_instance_type]
    instance_charge_type  = "PostPaid"
    spot_strategy         = "NoSpot"
    subnet_ids            = [bytepluscc_vpc_subnet.private["nodes"].subnet_id]
    public_access_enabled = false
    project_name          = var.project_name
    system_volume = {
      type = "ESSD_PL0"
      size = 80
    }
    security = {
      security_group_ids = bytepluscc_vke_cluster.dedicated.cluster_config.security_group_ids
      login = var.existing_ssh_key_pair_name == null ? null : {
        ssh_key_pair_name = var.existing_ssh_key_pair_name
      }
    }
  }
}

resource "bytepluscc_vpc_vpc" "dedicated" {
  vpc_name              = var.name
  cidr_block            = var.vpc_cidr
  project_name          = var.project_name
  enable_ipv_6          = false
  support_ipv_4_gateway = false
}

resource "bytepluscc_vpc_subnet" "private" {
  for_each = local.subnet_cidrs

  subnet_name  = "${var.name}-${each.key}"
  vpc_id       = bytepluscc_vpc_vpc.dedicated.vpc_id
  cidr_block   = each.value
  zone_id      = var.zone_id
  enable_ipv_6 = false
}

resource "bytepluscc_natgateway_ngw" "egress" {
  nat_gateway_name = "${var.name}-egress"
  vpc_id           = bytepluscc_vpc_vpc.dedicated.vpc_id
  subnet_id        = bytepluscc_vpc_subnet.private["edge"].subnet_id
  network_type     = "internet"
  billing_type     = 2
  spec             = "Small"
  project_name     = var.project_name
}

resource "bytepluscc_vpc_eip" "egress" {
  name                  = "${var.name}-egress"
  billing_type          = 3
  bandwidth             = var.nat_bandwidth_mbps
  isp                   = "BGP"
  instance_type         = "Nat"
  instance_id           = bytepluscc_natgateway_ngw.egress.nat_gateway_id
  project_name          = var.project_name
  release_with_instance = false
}

resource "bytepluscc_natgateway_snatentry" "private" {
  for_each = local.egress_subnets

  snat_entry_name = "${var.name}-${each.key}"
  nat_gateway_id  = bytepluscc_natgateway_ngw.egress.nat_gateway_id
  eip_id          = bytepluscc_vpc_eip.egress.allocation_id
  subnet_id       = each.value
}

resource "bytepluscc_vpc_route_table" "private_egress" {
  route_table_name = "${var.name}-private-egress"
  vpc_id           = bytepluscc_vpc_vpc.dedicated.vpc_id
  project_name     = var.project_name
  associate_type   = "Subnet"
  subnet_ids       = values(local.egress_subnets)
  custom_route_entries = [{
    route_entry_name           = "provider-egress"
    description                = "NAT egress for private nodes and VPC-CNI pods"
    destination_cidr_block     = "0.0.0.0/0"
    destination_prefix_list_id = null
    next_hop_id                = bytepluscc_natgateway_ngw.egress.nat_gateway_id
    next_hop_name              = bytepluscc_natgateway_ngw.egress.nat_gateway_name
    next_hop_type              = "NatGW"
  }]

  depends_on = [bytepluscc_natgateway_snatentry.private]
}

resource "bytepluscc_vke_cluster" "dedicated" {
  name                      = var.name
  description               = "Dedicated Seed MCP cluster with stateless application pods"
  project_name              = var.project_name
  kubernetes_version_create = var.kubernetes_version
  delete_protection_enabled = true
  cluster_config = {
    subnet_ids                             = [bytepluscc_vpc_subnet.private["nodes"].subnet_id]
    api_server_public_access_enabled       = false
    resource_public_access_default_enabled = false
  }
  pods_config = {
    pod_network_mode = "VpcCniShared"
    vpc_cni_config = {
      subnet_ids        = [bytepluscc_vpc_subnet.private["pods"].subnet_id]
      trunk_eni_enabled = false
    }
  }
  services_config = {
    service_cidrsv_4 = [var.service_cidr]
  }

  depends_on = [bytepluscc_vpc_route_table.private_egress]
}

resource "bytepluscc_vke_node_pool" "application" {
  # Fixed same-zone capacity is not AZ resilience or an application HPA sizing proof.
  name       = "${var.name}-workers"
  cluster_id = bytepluscc_vke_cluster.dedicated.cluster_id
  auto_scaling = {
    enabled          = false
    desired_replicas = var.node_count
  }
  node_config = local.worker_node_config
}

resource "bytepluscc_vke_node_pool" "burst" {
  count = var.burst_node_max_count > 0 ? 1 : 0

  name       = "${var.name}-burst-workers"
  cluster_id = bytepluscc_vke_cluster.dedicated.cluster_id
  auto_scaling = {
    enabled          = true
    desired_replicas = 0
    min_replicas     = 0
    max_replicas     = var.burst_node_max_count
    subnet_policy    = "ZoneBalance"
  }
  node_config = local.worker_node_config

  lifecycle {
    # Cluster Autoscaler owns only the burst count; Terraform retains its bounds.
    ignore_changes = [auto_scaling.desired_replicas]
  }
}
