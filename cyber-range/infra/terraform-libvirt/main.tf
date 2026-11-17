# One isolated network per segment. mode is absent (isolated) → libvirt does NOT
# forward to the host/internet, so arenas have no egress by construction (the
# Phase-2 containment guarantee, mirroring the AWS no-IGW posture). dnsmasq still
# serves DHCP within the segment so nodes get addresses.
resource "libvirt_network" "segment" {
  for_each  = { for s in var.segments : s.name => s }
  name      = "nv-${var.arena_id}-${each.key}"
  mode      = "none"
  autostart = true
  addresses = [each.value.cidr]
  dhcp { enabled = true }
}

locals {
  # A node lands on its first segment (multi-NIC straddle is a follow-up, as in
  # the AWS module).
  node_net = { for n in var.nodes : n.name => libvirt_network.segment[n.segments[0]].id }
}

# Per-node backing volume, copied from the (per-node or default) source image.
resource "libvirt_volume" "node" {
  for_each = { for n in var.nodes : n.name => n }
  name     = "nv-${var.arena_id}-${each.key}.qcow2"
  pool     = var.pool
  source   = coalesce(each.value.image, var.base_image)
  format   = "qcow2"
}

# Minimal cloud-init: hostname only. SSH-key injection for agent exec lands in
# the exec increment (libvirt has no docker-exec equivalent).
resource "libvirt_cloudinit_disk" "node" {
  for_each  = { for n in var.nodes : n.name => n }
  name      = "nv-${var.arena_id}-${each.key}-cloudinit.iso"
  pool      = var.pool
  user_data = <<-EOT
    #cloud-config
    hostname: ${each.key}
    preserve_hostname: false
  EOT
}

resource "libvirt_domain" "node" {
  for_each = { for n in var.nodes : n.name => n }
  name     = "nv-${var.arena_id}-${each.key}"
  memory   = each.value.memory
  vcpu     = each.value.vcpu

  cloudinit = libvirt_cloudinit_disk.node[each.key].id

  network_interface {
    network_id     = local.node_net[each.key]
    wait_for_lease = true
  }

  disk {
    volume_id = libvirt_volume.node[each.key].id
  }

  console {
    type        = "pty"
    target_port = "0"
  }

  graphics {
    type        = "vnc"
    listen_type = "address"
  }
}
