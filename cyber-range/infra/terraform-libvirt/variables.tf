variable "arena_id" {
  type        = string
  description = "Unique Nidavellir arena id; names + tags every resource."
}

variable "libvirt_uri" {
  type        = string
  default     = "qemu:///system"
  description = "libvirt connection URI (local KVM by default)."
}

variable "pool" {
  type        = string
  default     = "default"
  description = "libvirt storage pool that holds the arena's volumes."
}

variable "base_image" {
  type        = string
  description = "Source disk image (qcow2 URL or local path) for nodes whose logical image has no libvirt mapping — a cloud image with cloud-init."
}

variable "segments" {
  type = list(object({
    name = string
    cidr = string
  }))
  description = "Named network segments; one ISOLATED libvirt network is created per segment (no forwarding → no internet egress by construction, the containment guarantee)."
}

variable "nodes" {
  type = list(object({
    name       = string
    role       = string
    memory     = optional(number, 1024) # MiB
    vcpu       = optional(number, 1)
    segments   = list(string)
    ports      = optional(list(number), [])
    entrypoint = optional(bool, false)
    image      = optional(string) # per-node source image; falls back to base_image
  }))
  description = "The arena topology — one libvirt domain (VM) is created per node."
}
