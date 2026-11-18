variable "name" {
  description = "Dedicated VKE resource prefix for specs/SPEC_VKE_DEPLOYMENT.md."
  type        = string
  default     = "seed-mcp"
  nullable    = false
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,39}$", var.name))
    error_message = "Use a lowercase resource prefix of 2-40 letters, digits or hyphens."
  }
}

variable "fresh_state_confirmed" {
  description = "Acknowledge this is a separate fresh VKE state, never old ECS state. Preserve old state/backups for separately authorized retirement."
  type        = bool
  default     = false
  nullable    = false
  validation {
    condition     = var.fresh_state_confirmed
    error_message = "Confirm a separate fresh VKE backend/workspace. Never reuse or migrate old ECS state into this root."
  }
}

variable "region" {
  description = "BytePlus region with verified VKE, EBS, CLB and NAT availability."
  type        = string
  default     = "ap-southeast-1"
  nullable    = false
  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.region))
    error_message = "Use a valid regional identifier."
  }
}

variable "zone_id" {
  description = "Operator-verified zone with node inventory, compatible node system disks and NAT. Fixed same-zone nodes do not establish AZ-failure resilience."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^${var.region}-?[a-z]$", var.zone_id))
    error_message = "Supply an available zone in the selected region."
  }
}

variable "kubernetes_version" {
  description = "Operator-verified currently maintained regional VKE Kubernetes release >=1.30 in x.xx form, compatible with the chart and VKE-admin-owned addons. This floor does not establish regional availability or continued maintenance of 1.30."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^1\\.[0-9]{2}$", var.kubernetes_version)) && try(tonumber(split(".", var.kubernetes_version)[1]) >= 30, false)
    error_message = "Select an operator-verified currently maintained regional VKE release >=1.30 in x.xx form. The compatibility floor is not an availability or maintenance claim."
  }
}

variable "node_instance_type" {
  description = "One operator-verified regular on-demand instance type supporting ESSD_PL0 in the selected zone. VKE selects its supported veLinux image."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^ecs\\.[a-z0-9.-]+$", var.node_instance_type))
    error_message = "Supply an available ECS instance type for the VKE nodes."
  }
}

variable "node_count" {
  description = "Fixed node count, not app replicas; node autoscaling is disabled. Size application HPA against actual schedulable capacity including surge/draining pods; two same-zone nodes are not capacity or AZ-resilience certification."
  type        = number
  default     = 2
  nullable    = false
  validation {
    condition     = var.node_count >= 2 && var.node_count <= 10 && floor(var.node_count) == var.node_count
    error_message = "Use 2-10 whole on-demand nodes and verify application, surge and draining capacity separately."
  }
}

variable "project_name" {
  description = "Existing BytePlus project for cluster, network, nodes, EIP and EBS."
  type        = string
  default     = "default"
  nullable    = false
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{1,64}$", var.project_name))
    error_message = "Supply a project name of 1-64 letters, digits, underscores, dots or hyphens."
  }
}

variable "vpc_cidr" {
  description = "Dedicated canonical RFC1918 /16. Three nonoverlapping /20 subnets are derived for nodes, VPC-CNI pods and NAT/CLB."
  type        = string
  default     = "10.80.0.0/16"
  nullable    = false
  validation {
    condition     = try("${cidrhost(var.vpc_cidr, 0)}/16" == var.vpc_cidr, false) && can(regex("^(10\\.[0-9]{1,3}|172\\.(1[6-9]|2[0-9]|3[01])|192\\.168)\\.0\\.0/16$", var.vpc_cidr))
    error_message = "Use a canonical private IPv4 /16 in 10/8, 172.16/12 or 192.168/16."
  }
}

variable "service_cidr" {
  description = "Canonical RFC1918 /16 for Kubernetes Services, separate from the VPC. Verify no overlap with private operator networks."
  type        = string
  default     = "10.81.0.0/16"
  nullable    = false
  validation {
    condition     = try("${cidrhost(var.service_cidr, 0)}/16" == var.service_cidr, false) && can(regex("^(10\\.[0-9]{1,3}|172\\.(1[6-9]|2[0-9]|3[01])|192\\.168)\\.0\\.0/16$", var.service_cidr)) && var.service_cidr != var.vpc_cidr
    error_message = "Use a canonical private /16 different from the VPC /16."
  }
}

variable "existing_ssh_key_pair_name" {
  description = "Optional existing SSH key-pair name only when regional VKE creation requires login configuration. No private key or password is accepted."
  type        = string
  default     = null
  validation {
    condition     = var.existing_ssh_key_pair_name == null ? true : can(regex("^[A-Za-z0-9_.-]{1,64}$", var.existing_ssh_key_pair_name))
    error_message = "Supply only an existing key-pair name, never key material."
  }
}

variable "nat_bandwidth_mbps" {
  description = "NAT EIP traffic-billed bandwidth cap in Mbps for image pulls and fixed provider origins."
  type        = number
  default     = 25
  nullable    = false
  validation {
    condition     = var.nat_bandwidth_mbps >= 1 && var.nat_bandwidth_mbps <= 200 && floor(var.nat_bandwidth_mbps) == var.nat_bandwidth_mbps
    error_message = "Use a whole bandwidth cap of 1-200 Mbps."
  }
}
