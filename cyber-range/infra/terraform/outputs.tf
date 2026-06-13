# -------------------------------------------------------------------
# ----- OUTPUT TERRAFORM PER CYBER RANGE ITS -------------------------
# -------------------------------------------------------------------

# ========== VM LOG (MONITOR) ==========

output "log_vm_name" {
  description = "Nome della VM di logging/monitoring"
  value       = openstack_compute_instance_v2.cyber_guard_log.name
}

output "log_vm_private_ip" {
  description = "IP privato della VM di log"
  value       = openstack_networking_port_v2.log_vm_port.all_fixed_ips[0]
}

output "log_vm_floating_ip" {
  description = "IP pubblico (Floating IP) della VM di log"
  value       = openstack_networking_floatingip_v2.log_fip.address
}

output "log_vm_ssh_command" {
  description = "Comando SSH per connettersi alla VM di log"
  # MODIFICA: Rimosso path e nome dinamico, usato nome file statico
  value       = "ssh -i cyberguard_ssh_key.pem ubuntu@${openstack_networking_floatingip_v2.log_fip.address}"
}

# ========== VM ATTACK ==========

output "attack_vm_name" {
  description = "Nome della VM attaccante"
  value       = openstack_compute_instance_v2.cyber_guard_attack.name
}

output "attack_vm_private_ip" {
  description = "IP privato della VM attaccante"
  value       = openstack_networking_port_v2.vm_port.all_fixed_ips[0]
}

output "attack_vm_floating_ip" {
  description = "IP pubblico (Floating IP) della VM attaccante"
  value       = openstack_networking_floatingip_v2.attack_fip.address
}

output "attack_vm_ssh_command" {
  description = "Comando SSH per connettersi alla VM attaccante (Kali)"
  # MODIFICA: Rimosso ~/.ssh/ e ${var.keypair_name}, usato nome file statico
  value       = "ssh -i cyberguard_ssh_key.pem kali@${openstack_networking_floatingip_v2.attack_fip.address}"
}

# ========== VICTIM VM ==========

output "victim_vm_name" {
  description = "Nome della VM vittima"
  value       = openstack_compute_instance_v2.cyber_guard_victim.name
}

output "victim_vm_private_ip" {
  description = "IP privato della VM vittima"
  value       = openstack_networking_port_v2.victim_vm_port.all_fixed_ips[0]
}

output "victim_vm_floating_ip" {
  description = "IP pubblico della VM vittima"
  value       = openstack_networking_floatingip_v2.victim_fip.address
}

# ========== NETWORK INFO ==========

output "private_network_cidr" {
  description = "CIDR della rete privata"
  value       = var.private_cidr
}

output "private_network_name" {
  description = "Nome della rete privata"
  value       = openstack_networking_network_v2.networkcyberguard.name
}

output "router_name" {
  description = "Nome del router"
  value       = openstack_networking_router_v2.cyberguard_router.name
}

# ========== SOC CREDENTIALS ==========

output "soc_dashboard_url" {
  value = "https://${openstack_networking_floatingip_v2.log_fip.address}:5601"
}

output "soc_credentials" {
  value = {
    username = "cyberrange-admin"
    password = "CyberRange2024!"
  }
  sensitive = true
}

output "soc_installation_log" {
  value = "ssh ubuntu@${openstack_networking_floatingip_v2.log_fip.address} 'tail -f /var/log/soc_installation.log'"
}

# ========== ISTRUZIONI SETUP ==========

output "setup_instructions" {
  description = "Istruzioni per completare il setup"
  value = <<-EOT
  
  ╔════════════════════════════════════════════════════════════════╗
  ║         ITS CYBER RANGE - CLOUD INCIDENT SIMULATOR             ║
  ╚════════════════════════════════════════════════════════════════╝
  
   NETWORK INFO
  ├─ Rete privata:     ${var.private_cidr}
  ├─ Nome rete:        ${openstack_networking_network_v2.networkcyberguard.name}
  └─ Router:           ${openstack_networking_router_v2.cyberguard_router.name}
  
    VM LOG (Monitor & IDS)
  ├─ Nome:             ${openstack_compute_instance_v2.cyber_guard_log.name}
  ├─ IP Privato:       ${openstack_networking_port_v2.log_vm_port.all_fixed_ips[0]}
  ├─ IP Pubblico:      ${openstack_networking_floatingip_v2.log_fip.address}
  └─ SSH:              ssh -i cyberguard_ssh_key.pem ubuntu@${openstack_networking_floatingip_v2.log_fip.address}
  
    VM ATTACK (Kali Linux)
  ├─ Nome:             ${openstack_compute_instance_v2.cyber_guard_attack.name}
  ├─ IP Privato:       ${openstack_networking_port_v2.vm_port.all_fixed_ips[0]}
  ├─ IP Pubblico:      ${openstack_networking_floatingip_v2.attack_fip.address}
  └─ SSH:              ssh -i cyberguard_ssh_key.pem kali@${openstack_networking_floatingip_v2.attack_fip.address}
  
   PROSSIMI PASSI
  
  1️  Configura VM LOG (Suricata + Wazuh):
     ssh ubuntu@${openstack_networking_floatingip_v2.log_fip.address}
     sudo /opt/cyberrange/setup_suricata_wazuh.sh
  
  2️  Verifica installazione:
     systemctl status suricata wazuh-agent
     tail -f /var/log/suricata/eve.json | jq
  
  3️  Dalla VM Attack, testa la rete:
     ping ${openstack_networking_port_v2.log_vm_port.all_fixed_ips[0]}
  
  4️  Inizia le simulazioni di attacco (DVWA su VM victim)
  
   DOCUMENTAZIONE
  ├─ README VM Log:    cat /opt/cyberrange/README.md
  ├─ Log setup:        cat /var/log/cyberrange-setup.log
  └─ Stats Suricata:   /usr/local/bin/suricata_stats.sh
  
    IMPORTANTE: La chiave privata è salvata come:
     - cyberguard_ssh_key.pem
  
  EOT
}

# ========== QUICK COMMANDS ==========

output "quick_commands" {
  description = "Comandi rapidi per gestione Cyber Range"
  value = {
    ssh_log    = "ssh -i cyberguard_ssh_key.pem ubuntu@${openstack_networking_floatingip_v2.log_fip.address}"
    ssh_attack = "ssh -i cyberguard_ssh_key.pem kali@${openstack_networking_floatingip_v2.attack_fip.address}"
    
    setup_suricata     = "sudo /opt/cyberrange/setup_suricata_wazuh.sh"
    suricata_status    = "systemctl status suricata"
    suricata_logs      = "tail -f /var/log/suricata/eve.json | jq"
    suricata_stats     = "/usr/local/bin/suricata_stats.sh"
    
    wazuh_status       = "systemctl status wazuh-agent"
    wazuh_logs         = "tail -f /var/ossec/logs/ossec.log"
    
    test_connectivity  = "ping ${openstack_networking_port_v2.log_vm_port.all_fixed_ips[0]}"
  }
}