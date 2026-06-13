# -------------------------------------------------------------------
# --- OpenStack credentials ---
# -------------------------------------------------------------------
variable "os_project_domain" {
  description = "OpenStack project domain"
  type        = string
  default     = "Default"
}

variable "os_user_name" {
  description = "OpenStack username"
  type        = string
}

variable "os_user_domain" {
  description = "OpenStack user domain"
  type        = string
  default     = "Default"
}

variable "os_password" {
  description = "OpenStack user password"
  type        = string
  sensitive   = true
}

variable "os_auth_url" {
  description = "Keystone v3 URL"
  type        = string
}

variable "os_region" {
  description = "OpenStack region"
  type        = string
  default     = "RegionOne"
}

variable "os_insecure" {
  description = "Allow self-signed certificates"
  type        = bool
  default     = true
}

variable "os_tenant_id" {
  description = "Project (tenant) ID"
  type        = string
}

# -------------------------------------------------------------------
# --- Network ---
# -------------------------------------------------------------------
variable "external_network_name" {
  description = "Public network name (floating-IP pool)"
  type        = string
  default     = "OPENSTACK_SHARED_PUBLIC"
}

variable "net_name" {
  type    = string
  default = "networkcyberguard"
}

variable "subnet_name" {
  type    = string
  default = "networkcyberguard-subnet"
}

variable "private_cidr" {
  type    = string
  default = "192.168.0.0/24"
}

variable "pool_start" {
  type    = string
  default = "192.168.0.100"
}

variable "pool_end" {
  type    = string
  default = "192.168.0.200"
}

variable "dns_nameservers" {
  type    = list(string)
  default = ["8.8.8.8", "1.1.1.1"]
}

# -------------------------------------------------------------------
# --- VM / flavor configuration ---
# -------------------------------------------------------------------

# Base flavor for the Kali foothold and the victim (2GB is enough).
variable "flavor_name" {
  description = "Base flavor (e.g. t3.small)"
  type        = string
  default     = "t3.small"
}

# Larger flavor for the SOC/sensor node (Wazuh needs 4GB+).
variable "soc_flavor_name" {
  description = "Flavor for the SOC node (needs more RAM)"
  type        = string
  default     = "t3.medium"
}

variable "image_name" {
  description = "Kali image name"
  type        = string
  default     = "kali-linux-2025-cloud"
}

variable "vm_name" {
  description = "Virtual machine name"
  type        = string
  default     = "cyber_guard-attack"
}

variable "root_volume_gb" {
  description = "Root volume size (GB)"
  type        = number
  default     = 30
}

# -------------------------------------------------------------------
# --- Sensor / log VM ---
# -------------------------------------------------------------------
variable "log_image_name" {
  description = "Image name for the sensor/log VM"
  type        = string
  default     = "ubuntu_cloud"
}

variable "log_vm_name" {
  description = "Sensor/log VM name"
  type        = string
  default     = "cyber_guard_log"
}

variable "log_root_volume_gb" {
  description = "Root volume size for the sensor/log VM"
  type        = number
  default     = 40
}

# -------------------------------------------------------------------
# --- Victim VM ---
# NOTE: image default is a placeholder; re-imaged when scenarios move to the
# Phase-1 N-node topology schema. The scenario spec overrides it per deploy.
# -------------------------------------------------------------------
variable "victim_image_name" {
  description = "Image name for the victim VM"
  type        = string
  default     = "victim-web"
}

variable "victim_vm_name" {
  description = "Victim VM name"
  type        = string
  default     = "cyber_guard_victim"
}

variable "victim_root_volume_gb" {
  description = "Root volume size for the victim VM"
  type        = number
  default     = 30
}

# -------------------------------------------------------------------
# --- SSH / keypair ---
# -------------------------------------------------------------------
variable "keypair_name" {
  description = "Name of the SSH keypair in OpenStack"
  type        = string
  default     = "cyberguard_ssh_key"
}
