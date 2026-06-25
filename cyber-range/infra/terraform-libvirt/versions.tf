terraform {
  required_version = ">= 1.5"
  required_providers {
    libvirt = {
      source = "dmacvicar/libvirt"
      # Pinned to the stable classic schema (disk/network_interface/console blocks,
      # libvirt_network mode/addresses/dhcp). The 0.8/0.9 line is a schema rewrite
      # (devices/os structure) — migrating to it is a follow-up.
      version = "0.7.6"
    }
  }
}

provider "libvirt" {
  # Local hypervisor. qemu:///system talks to the host libvirtd (KVM); override
  # via the driver (LIBVIRT_URI) for a remote/socket-mounted daemon.
  uri = var.libvirt_uri
}
