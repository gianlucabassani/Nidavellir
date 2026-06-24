# -------------------------------------------------------------------
# ----- RETE PRIVATA (CLIENT + MGMT) --------------------------------
# -------------------------------------------------------------------

# Rete privata principale: conterrà Victim + Log/SOC
resource "openstack_networking_network_v2" "networknidavellir" {
  name           = var.net_name
  admin_state_up = true
}

# Subnet CLIENT -> Victim (e potenzialmente Log)
resource "openstack_networking_subnet_v2" "networknidavellir_subnet" {
  name            = var.subnet_name
  network_id      = openstack_networking_network_v2.networknidavellir.id
  cidr            = var.private_cidr
  ip_version      = 4
  enable_dhcp     = true
  dns_nameservers = var.dns_nameservers

  allocation_pool {
    start = var.pool_start
    end   = var.pool_end
  }
}

# Subnet MANAGEMENT -> Blue Team / Wazuh / SOC
resource "openstack_networking_subnet_v2" "mgmt_subnet" {
  name            = "mgmt-subnet"
  network_id      = openstack_networking_network_v2.networknidavellir.id
  cidr            = "192.168.30.0/24"
  ip_version      = 4
  enable_dhcp     = true
  dns_nameservers = var.dns_nameservers
}

# Subnet ATTACKER (vecchia) -> Lab / Red Team sulla rete principale
resource "openstack_networking_subnet_v2" "attacker_subnet" {
  name            = "attacker-subnet"
  network_id      = openstack_networking_network_v2.networknidavellir.id
  cidr            = "192.168.20.0/24"
  ip_version      = 4
  enable_dhcp     = true
  dns_nameservers = var.dns_nameservers
}

# -------------------------------------------------------------------
# ----- RETE PRIVATA (ATTACK SEPARATA) ------------------------------
# -------------------------------------------------------------------

# Nuova rete separata per l'attaccante (Kali)
resource "openstack_networking_network_v2" "network_attack" {
  name           = "network-attack"
  admin_state_up = true
}

# Subnet della nuova rete degli attaccanti
resource "openstack_networking_subnet_v2" "network_attack_subnet" {
  name       = "network-attack-subnet"
  network_id = openstack_networking_network_v2.network_attack.id

  cidr        = "192.168.50.0/24"
  ip_version  = 4
  gateway_ip  = "192.168.50.1"
  enable_dhcp = true

  dns_nameservers = [
    "8.8.8.8",
    "1.1.1.1",
  ]
}

# -------------------------------------------------------------------
# ----- RETE PUBBLICA (DATA SOURCE) ---------------------------------
# -------------------------------------------------------------------

# Rete esterna (pubblica) - data source
data "openstack_networking_network_v2" "external" {
  name = var.external_network_name
}

# -------------------------------------------------------------------
# ----- ROUTER E INTERFACCE -----------------------------------------
# -------------------------------------------------------------------

# Router verso rete pubblica
resource "openstack_networking_router_v2" "nidavellir_router" {
  name                = "nidavellir_router"
  admin_state_up      = true
  external_network_id = data.openstack_networking_network_v2.external.id
}

# Interfaccia router sulla subnet CLIENT
resource "openstack_networking_router_interface_v2" "nidavellir_router_iface" {
  router_id = openstack_networking_router_v2.nidavellir_router.id
  subnet_id = openstack_networking_subnet_v2.networknidavellir_subnet.id
}

# Interfaccia router sulla subnet MANAGEMENT (Blue Team / Wazuh)
resource "openstack_networking_router_interface_v2" "mgmt_router_iface" {
  router_id = openstack_networking_router_v2.nidavellir_router.id
  subnet_id = openstack_networking_subnet_v2.mgmt_subnet.id
}

# Interfaccia router sulla subnet ATTACKER (vecchia)
resource "openstack_networking_router_interface_v2" "attacker_router_iface" {
  router_id = openstack_networking_router_v2.nidavellir_router.id
  subnet_id = openstack_networking_subnet_v2.attacker_subnet.id
}

# Interfaccia router sulla NUOVA subnet degli attaccanti (network-attack)
resource "openstack_networking_router_interface_v2" "nidavellir_router_attack" {
  router_id = openstack_networking_router_v2.nidavellir_router.id
  subnet_id = openstack_networking_subnet_v2.network_attack_subnet.id
}

# -------------------------------------------------------------------
# ----- SECURITY GROUP E REGOLE ------------------------------------
# -------------------------------------------------------------------

# Security Group base (SSH + ICMP)
resource "openstack_networking_secgroup_v2" "nidavellir_sg" {
  name        = "nidavellir-secgroup"
  description = "Allow SSH and ICMP"
}

resource "openstack_networking_secgroup_rule_v2" "ssh_in" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.nidavellir_sg.id
}

resource "openstack_networking_secgroup_rule_v2" "icmp_in" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "icmp"
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.nidavellir_sg.id
}

# HTTP (porta 80)
resource "openstack_networking_secgroup_rule_v2" "http_in" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 80
  port_range_max    = 80
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.nidavellir_sg.id
}

# HTTPS (porta 443)
resource "openstack_networking_secgroup_rule_v2" "https_in" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 443
  port_range_max    = 443
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.nidavellir_sg.id
}

# Security Group per la MANAGEMENT (Blue Team / Wazuh / SOC)
resource "openstack_networking_secgroup_v2" "mgmt_sg" {
  name        = "mgmt-secgroup"
  description = "Security Group per Management / Blue Team (Wazuh, SOC)"
}

# Regola: accetta log Wazuh dagli agent sulla NUOVA rete degli attaccanti
resource "openstack_networking_secgroup_rule_v2" "allow_wazuh_agent_from_lab" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 1514
  port_range_max    = 1515
  remote_ip_prefix  = "192.168.50.0/24"
  security_group_id = openstack_networking_secgroup_v2.mgmt_sg.id
}

# Regola Wazuh Dashboard (5601)
resource "openstack_networking_secgroup_rule_v2" "wazuh_dashboard_in" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 5601
  port_range_max    = 5601
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.nidavellir_sg.id
}

# NOTA: Le risorse "openstack_networking_port_v2" sono state rimosse da qui
# e spostate in compute.tf per gestire le dipendenze degli IP.