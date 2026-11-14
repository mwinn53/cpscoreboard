# Startup listener (issue #50): while the server is stopped, a daily Lambda checks
# whether the public scoreboard is back and emails the admin a signed link to start
# the server. Code: lambda/startup_listener.py. Costs about $0 (free-tier Lambda and
# Scheduler). Needs SES (mail_domain/mail_sender) and ADMIN_NOTIFY_EMAIL.

locals {
  listener_enabled = local.ses_enabled && var.mail_sender != "" && lookup(var.app_settings, "ADMIN_NOTIFY_EMAIL", "") != ""
  listener_name    = "${var.name}-startup-listener"
  listener_params  = "/${var.name}/startup-listener"
}

data "archive_file" "startup_listener" {
  count       = local.listener_enabled ? 1 : 0
  type        = "zip"
  source_file = "${path.module}/lambda/startup_listener.py"
  output_path = "${path.module}/.build/startup_listener.zip"
}

resource "aws_cloudwatch_log_group" "startup_listener" {
  count             = local.listener_enabled ? 1 : 0
  name              = "/aws/lambda/${local.listener_name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "startup_listener" {
  count              = local.listener_enabled ? 1 : 0
  name               = local.listener_name
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "startup_listener" {
  count = local.listener_enabled ? 1 : 0
  statement {
    sid       = "SeeTheInstance"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"] # DescribeInstances doesn't support resource-level permissions
  }
  statement {
    sid       = "StartOnlyThisInstance"
    actions   = ["ec2:StartInstances"]
    resources = [aws_instance.web.arn]
  }
  statement {
    sid       = "EmailTheAdmin"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = [aws_sesv2_email_identity.domain[0].arn]
  }
  statement {
    sid       = "OwnState"
    actions   = ["ssm:GetParameter", "ssm:PutParameter"]
    resources = ["arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${local.listener_params}/*"]
  }
  statement {
    sid       = "OwnUrl"
    actions   = ["lambda:GetFunctionUrlConfig"]
    resources = ["arn:aws:lambda:${var.region}:${data.aws_caller_identity.current.account_id}:function:${local.listener_name}"]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.startup_listener[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "startup_listener" {
  count  = local.listener_enabled ? 1 : 0
  name   = "startup-listener"
  role   = aws_iam_role.startup_listener[0].id
  policy = data.aws_iam_policy_document.startup_listener[0].json
}

resource "aws_lambda_function" "startup_listener" {
  count                          = local.listener_enabled ? 1 : 0
  function_name                  = local.listener_name
  description                    = "Emails a start link when the public scoreboard is back and the server is stopped"
  role                           = aws_iam_role.startup_listener[0].arn
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  handler                        = "startup_listener.handler"
  filename                       = data.archive_file.startup_listener[0].output_path
  source_code_hash               = data.archive_file.startup_listener[0].output_base64sha256
  timeout                        = 30
  memory_size                    = 128
  reserved_concurrent_executions = 2 # the link is public; this caps any abuse

  environment {
    variables = {
      INSTANCE_ID    = aws_instance.web.id
      SCOREBOARD_URL = lookup(var.app_settings, "SCOREBOARD_URL", "https://scoreboard.uscyberpatriot.org/api/team/scores.php")
      MAIL_FROM      = var.mail_sender
      MAIL_TO        = var.app_settings["ADMIN_NOTIFY_EMAIL"]
      SITE_URL       = local.site_url
      SITE_TITLE     = lookup(var.app_settings, "SITE_TITLE", "EMS CyberPatriot Next Generation Scorebot")
      PARAM_PREFIX   = local.listener_params
    }
  }

  depends_on = [aws_cloudwatch_log_group.startup_listener, aws_iam_role_policy.startup_listener]
}

# The emailed link. Public by design: every request needs a valid signed token, and
# only a POST from the confirmation page starts anything.
resource "aws_lambda_function_url" "startup_listener" {
  count              = local.listener_enabled ? 1 : 0
  function_name      = aws_lambda_function.startup_listener[0].function_name
  authorization_type = "NONE"
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "startup_listener_scheduler" {
  count              = local.listener_enabled ? 1 : 0
  name               = "${local.listener_name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "startup_listener_scheduler" {
  count = local.listener_enabled ? 1 : 0
  name  = "invoke"
  role  = aws_iam_role.startup_listener_scheduler[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.startup_listener[0].arn
    }]
  })
}

resource "aws_scheduler_schedule" "startup_listener" {
  count                        = local.listener_enabled ? 1 : 0
  name                         = local.listener_name
  description                  = "Daily: is the public scoreboard back while the server is stopped?"
  schedule_expression          = "cron(0 14 * * ? *)" # 14:00 UTC = 9 or 10 AM Eastern
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.startup_listener[0].arn
    role_arn = aws_iam_role.startup_listener_scheduler[0].arn
    input    = jsonencode({ source = "schedule" })
  }
}

output "startup_listener" {
  description = "How to test the startup listener."
  value = !local.listener_enabled ? "Startup listener off (needs mail_domain, mail_sender and ADMIN_NOTIFY_EMAIL)" : join("\n", [
    "Function: ${local.listener_name} (daily at 14:00 UTC)",
    "Run a check now: aws lambda invoke --function-name ${local.listener_name} --payload '{}' --cli-binary-format raw-in-base64-out out.json && cat out.json",
  ])
}
