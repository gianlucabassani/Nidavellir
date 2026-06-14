# Resolve an AMI for every node that gave a name filter instead of a fixed id.
data "aws_ami" "node" {
  for_each = { for n in var.nodes : n.name => n if n.ami == null }

  most_recent = true
  owners      = [coalesce(each.value.ami_owner, var.default_ami_owner)]

  filter {
    name   = "name"
    values = [coalesce(each.value.ami_name, var.default_ami_name)]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  # Fixed id wins; otherwise the looked-up AMI.
  node_ami = {
    for n in var.nodes : n.name => (
      n.ami != null ? n.ami : data.aws_ami.node[n.name].id
    )
  }
  # A node lands in its first segment's subnet (multi-NIC straddle is a
  # follow-up — see SCENARIOS.md).
  node_subnet = {
    for n in var.nodes : n.name => aws_subnet.segment[n.segments[0]].id
  }
}

resource "aws_instance" "node" {
  for_each = { for n in var.nodes : n.name => n }

  ami                         = local.node_ami[each.key]
  instance_type               = each.value.instance_type
  subnet_id                   = local.node_subnet[each.key]
  vpc_security_group_ids      = [aws_security_group.arena.id]
  associate_public_ip_address = var.associate_public_ip
  key_name                    = var.key_name

  tags = {
    Name                  = "cyberguard-${var.arena_id}-${each.key}"
    "cyberguard:arena_id" = var.arena_id
    "cyberguard:role"     = each.value.role
    "cyberguard:node"     = each.key
  }
}
