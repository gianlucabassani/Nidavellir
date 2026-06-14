variable "arena_id" {
  type        = string
  description = "Unique CyberGuard arena id; tags every resource as cyberguard:arena_id."
}

variable "vpc_cidr" {
  type        = string
  default     = "10.20.0.0/16"
  description = "Address space for the arena VPC; segments carve /24s out of it."
}

variable "associate_public_ip" {
  type        = bool
  default     = false
  description = "Off by default — arenas have no internet egress (no IGW/NAT created)."
}

variable "key_name" {
  type        = string
  default     = null
  description = "Optional EC2 key pair; SSM is the intended access path (no inbound SSH)."
}

variable "default_ami_name" {
  type        = string
  default     = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
  description = "AMI name filter for nodes whose image has no AWS mapping."
}

variable "default_ami_owner" {
  type        = string
  default     = "099720109477" # Canonical
  description = "AMI owner account for the default AMI lookup."
}

variable "segments" {
  type = list(object({
    name = string
    cidr = string
  }))
  description = "Named network segments; one subnet is created per segment."
}

variable "nodes" {
  type = list(object({
    name          = string
    role          = string
    instance_type = string
    segments      = list(string)
    ports         = optional(list(number), [])
    entrypoint    = optional(bool, false)
    ami           = optional(string) # fixed AMI id; wins over the name lookup
    ami_name      = optional(string) # AMI name filter for a data lookup
    ami_owner     = optional(string) # AMI owner account for the lookup
  }))
  description = "The arena topology — one EC2 instance is created per node."
}
