resource "aws_vpc" "arena" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name                  = "nidavellir-${var.arena_id}"
    "nidavellir:arena_id" = var.arena_id
  }
}

resource "aws_subnet" "segment" {
  for_each = { for s in var.segments : s.name => s }

  vpc_id     = aws_vpc.arena.id
  cidr_block = each.value.cidr

  tags = {
    Name                  = "nidavellir-${var.arena_id}-${each.key}"
    "nidavellir:arena_id" = var.arena_id
    "nidavellir:segment"  = each.key
  }
}

# No internet gateway / NAT is created: arena nodes have no route off the VPC,
# so there is no internet egress by construction (the Phase 2 containment
# guarantee). The security group additionally confines traffic to the VPC.
resource "aws_security_group" "arena" {
  name        = "nidavellir-${var.arena_id}"
  description = "Intra-arena traffic for Nidavellir arena ${var.arena_id}"
  vpc_id      = aws_vpc.arena.id

  ingress {
    description = "all traffic within the arena VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "egress confined to the arena VPC (no internet)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = {
    Name                  = "nidavellir-${var.arena_id}"
    "nidavellir:arena_id" = var.arena_id
  }
}
