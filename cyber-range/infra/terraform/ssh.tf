# -------------------------------------------------------------------
# --- CHIAVE SSH GESTITA DA TERRAFORM -------------------------------
# -------------------------------------------------------------------

# Genera una chiave privata RSA 4096 bit
resource "tls_private_key" "nidavellir_ssh_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

# Salva la chiave pubblica in un file (per usarla con ssh)
resource "local_file" "nidavellir_public_key" {
  content  = tls_private_key.nidavellir_ssh_key.public_key_openssh
  filename = "${path.module}/nidavellir_ssh_key.pub"
}

# Salva la chiave privata in un file locale, con permessi 0600
resource "local_sensitive_file" "nidavellir_private_key" {
  content         = tls_private_key.nidavellir_ssh_key.private_key_openssh
  filename        = "${path.module}/nidavellir_ssh_key.pem"
  file_permission = "0600"
}

# Keypair su OpenStack creata a partire dalla chiave pubblica
resource "openstack_compute_keypair_v2" "nidavellir_ssh_keypair" {
  name       = var.keypair_name
  public_key = tls_private_key.nidavellir_ssh_key.public_key_openssh
}

# Output utile se vuoi vedere i nomi
output "ssh_keypair_name" {
  value = var.keypair_name
}

output "ssh_public_key_path" {
  value = "${path.module}/nidavellir_ssh_key.pub"
}

output "ssh_private_key_path" {
  value = "${path.module}/nidavellir_ssh_key.pem"
}
