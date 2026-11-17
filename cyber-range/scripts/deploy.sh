#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/../infra/terraform"
terraform init
terraform plan -var-file=envs/dev/terraform.tfvars
terraform apply -var-file=envs/dev/terraform.tfvars -auto-approve
