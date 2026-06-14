terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  # Region and credentials come from the environment (AWS_REGION,
  # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, or an instance role).
  # No static configuration here — nothing secret in the module.
}
