# -------------------------------------------------------------------
# ----- DATASOURCES --------------------------------------------------
# -------------------------------------------------------------------
data "openstack_images_image_v2" "ubuntu_cloud" {
  name        = var.log_image_name
  most_recent = true
}

data "template_file" "soc_user_data" {
  template = file("${path.module}/user_data/soc_install.sh")
  vars = {
    network_interface  = "ens3"
    home_net           = "192.168.0.0/24"
    dashboard_user     = "cyberrange-admin"
    dashboard_password = "CyberRange2024!"
  }
}

data "local_file" "victim_agent_script" {
  filename = "${path.module}/user_data/install_victim_agent.sh"
}

# -------------------------------------------------------------------
# ----- VM LOG (BLUE TEAM) - SOC ------------------------------------
# -------------------------------------------------------------------
resource "openstack_networking_port_v2" "log_vm_port" {
  name               = "nidavellir-log-port"
  network_id         = openstack_networking_network_v2.networknidavellir.id
  admin_state_up     = true
  security_group_ids = [openstack_networking_secgroup_v2.nidavellir_sg.id]
  fixed_ip {
    subnet_id = openstack_networking_subnet_v2.networknidavellir_subnet.id
  }
  depends_on = [openstack_networking_router_interface_v2.nidavellir_router_iface]
}

resource "openstack_compute_instance_v2" "nidavellir_log" {
  name        = var.log_vm_name
  flavor_name = var.soc_flavor_name 
  key_pair    = openstack_compute_keypair_v2.nidavellir_ssh_keypair.name

  block_device {
    uuid                  = data.openstack_images_image_v2.ubuntu_cloud.id
    source_type           = "image"
    destination_type      = "volume"
    volume_size           = var.log_root_volume_gb
    boot_index            = 0
    delete_on_termination = true
  }

  network { 
    port = openstack_networking_port_v2.log_vm_port.id 
  }
  
  user_data = data.template_file.soc_user_data.rendered
  
  timeouts {
    create = "20m"
    delete = "20m"
  }

  depends_on = [openstack_networking_port_v2.log_vm_port]
}

resource "openstack_networking_floatingip_v2" "log_fip" {
  pool = data.openstack_networking_network_v2.external.name
}

resource "openstack_networking_floatingip_associate_v2" "log_fip_assoc" {
  floating_ip = openstack_networking_floatingip_v2.log_fip.address
  port_id     = openstack_networking_port_v2.log_vm_port.id
  depends_on  = [
    openstack_networking_router_interface_v2.nidavellir_router_iface,
    openstack_compute_instance_v2.nidavellir_log
  ]
}

# -------------------------------------------------------------------
# ----- VM ATTACK (RED TEAM) ----------------------------------------
# -------------------------------------------------------------------
resource "openstack_networking_port_v2" "vm_port" {
  name               = "nidavellir-attack-port"
  network_id         = openstack_networking_network_v2.network_attack.id
  admin_state_up     = true
  security_group_ids = [openstack_networking_secgroup_v2.nidavellir_sg.id]
  fixed_ip {
    subnet_id = openstack_networking_subnet_v2.network_attack_subnet.id
  }
  depends_on = [openstack_networking_router_interface_v2.nidavellir_router_attack]
}

resource "openstack_compute_instance_v2" "nidavellir_attack" {
  name        = var.vm_name
  flavor_name = var.flavor_name 
  key_pair    = openstack_compute_keypair_v2.nidavellir_ssh_keypair.name

  block_device {
    uuid                  = data.openstack_images_image_v2.kali.id
    source_type           = "image"
    destination_type      = "volume"
    volume_size           = var.root_volume_gb
    boot_index            = 0
    delete_on_termination = true
  }

  network { 
    port = openstack_networking_port_v2.vm_port.id 
  }

  timeouts {
    create = "20m"
    delete = "20m"
  }

  depends_on = [openstack_networking_port_v2.vm_port]
}

resource "openstack_networking_floatingip_v2" "attack_fip" {
  pool = data.openstack_networking_network_v2.external.name
}

resource "openstack_networking_floatingip_associate_v2" "attack_fip_assoc" {
  floating_ip = openstack_networking_floatingip_v2.attack_fip.address
  port_id     = openstack_networking_port_v2.vm_port.id
  depends_on  = [
    openstack_networking_router_interface_v2.nidavellir_router_attack,
    openstack_compute_instance_v2.nidavellir_attack
  ]
}

# -------------------------------------------------------------------
# ----- VM VICTIM (TARGET) ------------------------------------------
# -------------------------------------------------------------------
resource "openstack_networking_port_v2" "victim_vm_port" {
  name               = "nidavellir-victim-port"
  network_id         = openstack_networking_network_v2.networknidavellir.id
  admin_state_up     = true
  security_group_ids = [openstack_networking_secgroup_v2.nidavellir_sg.id]
  fixed_ip {
    subnet_id = openstack_networking_subnet_v2.networknidavellir_subnet.id
  }
  depends_on = [openstack_networking_router_interface_v2.nidavellir_router_iface]
}

resource "openstack_compute_instance_v2" "nidavellir_victim" {
  name        = var.victim_vm_name
  flavor_name = var.flavor_name
  key_pair    = openstack_compute_keypair_v2.nidavellir_ssh_keypair.name

  block_device {
    uuid                  = data.openstack_images_image_v2.victim.id
    source_type           = "image"
    destination_type      = "volume"
    volume_size           = var.victim_root_volume_gb
    boot_index            = 0
    delete_on_termination = true
  }

  network { 
    port = openstack_networking_port_v2.victim_vm_port.id 
  }
  
  user_data = <<EOF
#!/bin/bash
export WAZUH_MANAGER_IP="${openstack_networking_port_v2.log_vm_port.all_fixed_ips[0]}"
export AGENT_NAME="victim-web"
export OS_TYPE="linux"
${data.local_file.victim_agent_script.content}
EOF

  timeouts {
    create = "20m"
    delete = "20m"
  }

  depends_on = [
    openstack_networking_port_v2.victim_vm_port, 
    openstack_compute_instance_v2.nidavellir_log
  ]
}

resource "openstack_networking_floatingip_v2" "victim_fip" {
  pool = data.openstack_networking_network_v2.external.name
}

resource "openstack_networking_floatingip_associate_v2" "victim_fip_assoc" {
  floating_ip = openstack_networking_floatingip_v2.victim_fip.address
  port_id     = openstack_networking_port_v2.victim_vm_port.id
  depends_on  = [
    openstack_networking_router_interface_v2.nidavellir_router_iface,
    openstack_compute_instance_v2.nidavellir_victim
  ]
}