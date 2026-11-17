# The driver (providers/aws.py) flattens these per-node maps into the
# node_<name>_* output contract the other providers emit.

output "provider" {
  value = "aws"
}

output "arena_vpc_id" {
  value = aws_vpc.arena.id
}

output "node_private_ips" {
  value = { for k, i in aws_instance.node : k => i.private_ip }
}

output "node_instance_ids" {
  value = { for k, i in aws_instance.node : k => i.id }
}

output "node_roles" {
  value = { for n in var.nodes : n.name => n.role }
}
