# --- Container registry ---

resource "aws_ecr_repository" "app" {
  name                 = var.name
  image_tag_mutability = "MUTABLE" # :latest moves; deploys use the immutable :<git sha> tag

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# --- Logs (Docker awslogs driver) ---

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.name}"
  retention_in_days = var.log_retention_days
}

# --- Daily snapshots of the /data volume ---

data "aws_iam_policy_document" "dlm_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dlm" {
  name               = "${var.name}-dlm"
  assume_role_policy = data.aws_iam_policy_document.dlm_assume.json
}

resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "data" {
  description        = "Daily snapshots of ${var.name} data volume"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]
    target_tags = {
      Snapshot = var.name
    }

    schedule {
      name      = "daily"
      copy_tags = true

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["07:00"] # UTC, overnight in the US
      }

      retain_rule {
        count = var.snapshot_retain_count
      }
    }
  }
}

# --- App settings: /<name>/env/<KEY> → container environment ---
# Secrets are NOT managed here (they'd land in Terraform state). Add them by hand
# as SecureString parameters under the same path; deploys pick them up.

locals {
  managed_env = merge(var.app_settings, {
    SITE_ADDRESS = local.site_address
    ACME_EMAIL   = var.acme_email
    LOG_GROUP    = aws_cloudwatch_log_group.app.name
    # For the outage alert email and the admin "shut down" button (app/server_control.py).
    PUBLIC_URL      = local.site_url
    AWS_INSTANCE_ID = aws_instance.web.id
    DATA_VOLUME_ID  = aws_ebs_volume.data.id
    }, var.mail_sender == "" ? {} : {
    MAIL_FROM = var.mail_sender
  })
}

resource "aws_ssm_parameter" "env" {
  for_each = local.managed_env
  name     = "/${var.name}/env/${each.key}"
  type     = "String"
  value    = each.value
}
