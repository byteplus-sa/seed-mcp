output "cluster_id" {
  description = "Dedicated VKE cluster identifier, not a kubeconfig or API credential."
  value       = bytepluscc_vke_cluster.dedicated.cluster_id
}

output "node_pool_id" {
  description = "Fixed on-demand worker pool identifier."
  value       = bytepluscc_vke_node_pool.application.node_pool_id
}

output "network_ids" {
  description = "Infrastructure identifiers for operator route/SNAT verification. No application credentials."
  value = {
    vpc_id         = bytepluscc_vpc_vpc.dedicated.vpc_id
    subnet_ids     = { for name, subnet in bytepluscc_vpc_subnet.private : name => subnet.subnet_id }
    nat_gateway_id = bytepluscc_natgateway_ngw.egress.nat_gateway_id
    nat_eip_id     = bytepluscc_vpc_eip.egress.allocation_id
    route_table_id = bytepluscc_vpc_route_table.private_egress.route_table_id
  }
}

output "helm_infrastructure_values" {
  description = "Safe partial Helm inputs, not deployment approval. Admin must verify private access, Running VKE-admin-owned CCM, Ready nodes with surge/draining capacity, metrics API and existing identity/TLS Secrets before setting prerequisitesConfirmed=true. Preserve legacy volumes and VKE-admin-owned CSI; source changes do not decommission cloud resources."
  value = {
    prerequisitesConfirmed = false
    service = {
      subnetId = bytepluscc_vpc_subnet.private["edge"].subnet_id
    }
  }
}
