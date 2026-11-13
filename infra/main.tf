# One EC2 instance running Docker Compose (app + Caddy), with app data on a
# separate EBS volume so the instance can be replaced without losing it.

data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnet" "default" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = var.availability_zone
  default_for_az    = true
}

data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

locals {
  account_id    = data.aws_caller_identity.current.account_id
  sslip_address = "${replace(aws_eip.web.public_ip, ".", "-")}.sslip.io"
  # Caddy serves (and gets certificates for) every listed address. Keeping the sslip.io name
  # alongside a custom hostname means the site stays reachable while DNS changes propagate.
  site_address = var.site_hostname == "" ? local.sslip_address : "${var.site_hostname}, ${local.sslip_address}"
  site_url     = "https://${var.site_hostname == "" ? local.sslip_address : var.site_hostname}"
}

resource "aws_security_group" "web" {
  name        = "${var.name}-web"
  description = "HTTP/HTTPS in; all out. No SSH: use SSM Session Manager."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP (ACME challenges, redirect to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.http_cidrs != null ? var.http_cidrs : var.allowed_cidrs
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  ingress {
    description = "HTTP/3"
    from_port   = 443
    to_port     = 443
    protocol    = "udp"
    cidr_blocks = var.allowed_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ebs_volume" "data" {
  availability_zone = var.availability_zone
  size              = var.data_volume_size
  type              = "gp3"
  encrypted         = true

  tags = {
    Name     = "${var.name}-data"
    Snapshot = var.name # selects this volume for the DLM snapshot policy
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_instance" "web" {
  ami                         = data.aws_ssm_parameter.al2023_arm64.value
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnet.default.id
  vpc_security_group_ids      = [aws_security_group.web.id]
  iam_instance_profile        = aws_iam_instance_profile.web.name
  associate_public_ip_address = true

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    volume_serial   = replace(aws_ebs_volume.data.id, "-", "")
    compose_version = "v2.29.7"
  })

  metadata_options {
    http_tokens                 = "required"
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 2 # containers sit one hop further away; the app needs the role for SES
  }

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  tags = {
    Name = var.name
  }

  lifecycle {
    # New AMI releases shouldn't replace the server on every plan.
    # Replace deliberately with: terraform apply -replace=aws_instance.web
    ignore_changes = [ami, user_data]
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.web.id
}

resource "aws_eip" "web" {
  domain = "vpc"
  tags = {
    Name = var.name
  }
}

resource "aws_eip_association" "web" {
  instance_id   = aws_instance.web.id
  allocation_id = aws_eip.web.id
}
