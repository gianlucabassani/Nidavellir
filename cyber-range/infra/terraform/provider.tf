terraform {
  required_version = ">= 1.0"

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = ">= 3.0.0"
    }

    tls = {
      source  = "hashicorp/tls"
      version = ">= 4.0.0"
    }

    local = {
      source  = "hashicorp/local"
      version = ">= 2.0.0"
    }
  }
}

provider "openstack" {
  user_name        = var.os_user_name
  user_domain_name = var.os_user_domain
  password         = var.os_password

  # QUESTA RIGA È FONDAMENTALE:
  project_domain_name = var.os_project_domain

  auth_url  = var.os_auth_url
  region    = var.os_region
  insecure  = var.os_insecure
  tenant_id = var.os_tenant_id
}