# The driver (providers/libvirt.py) flattens these per-node maps into the
# node_<name>_* output contract the other providers emit.

output "provider" {
  value = "libvirt"
}

output "node_private_ips" {
  # First leased address on the node's NIC (wait_for_lease=true). Empty until the
  # guest DHCPs — captured at apply time.
  value = {
    for k, d in libvirt_domain.node :
    k => try(d.network_interface[0].addresses[0], "")
  }
}

output "node_instance_ids" {
  value = { for k, d in libvirt_domain.node : k => d.id }
}

output "node_roles" {
  value = { for n in var.nodes : n.name => n.role }
}
