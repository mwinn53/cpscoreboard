terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }

  # State lives in S3 (versioned, encrypted, private), with S3-native locking.
  # The bucket was created by hand, outside this config, so Terraform can't delete
  # its own state.
  backend "s3" {
    bucket       = "cpscoreboard-tfstate-224066956748"
    key          = "cpscoreboard/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.name
      ManagedBy = "terraform"
    }
  }
}
