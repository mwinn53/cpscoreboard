variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  description = "Prefix for resource names, the SSM parameter path (/<name>/env/) and the log group."
  type        = string
  default     = "cpscoreboard"
}

variable "github_repo" {
  description = "GitHub repository allowed to deploy, as owner/repo."
  type        = string
}

variable "deploy_branch" {
  description = "Only workflow runs on this branch can assume the deploy role."
  type        = string
  default     = "master"
}

variable "create_github_oidc_provider" {
  description = "Set to false if the account already has the token.actions.githubusercontent.com OIDC provider."
  type        = bool
  default     = true
}

variable "availability_zone" {
  description = "The instance and its data volume must share one AZ."
  type        = string
  default     = "us-east-1a"
}

variable "instance_type" {
  description = "Must be an ARM (Graviton) type; the image is built for linux/arm64."
  type        = string
  default     = "t4g.small"
}

variable "data_volume_size" {
  description = "GiB for the /data volume (database, TLS certificates)."
  type        = number
  default     = 10
}

variable "snapshot_retain_count" {
  description = "Number of daily /data snapshots to keep."
  type        = number
  default     = 7
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "acme_email" {
  description = "Contact email for Let's Encrypt/ZeroSSL certificate notices."
  type        = string
}

variable "allowed_cidrs" {
  description = "Who can reach the site on 443 (HTTPS/HTTP3). [\"0.0.0.0/0\"] = public."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "http_cidrs" {
  description = <<-EOT
    Who can reach port 80 (ACME HTTP-01 challenges + redirect to HTTPS). null = same as allowed_cidrs.
    Certificates can only be issued/renewed if Let's Encrypt can reach port 80 (or 443), so set
    this to ["0.0.0.0/0"] to keep certificates working while the site itself stays restricted.
  EOT
  type        = list(string)
  default     = null
}

variable "site_hostname" {
  description = "Custom hostname for the site (e.g. scores.example.com); its A record must point at the Elastic IP. Empty = sslip.io only."
  type        = string
  default     = ""
}

variable "mail_domain" {
  description = "Domain to send email from via SES (e.g. example.com). Empty = no SES."
  type        = string
  default     = ""
}

variable "mail_from_subdomain" {
  description = "Subdomain of mail_domain used as the SES envelope sender (bounces). Must not already have an MX or CNAME."
  type        = string
  default     = "bounce"
}

variable "mail_sender" {
  description = "From address for app email, e.g. noreply@example.com (must be in mail_domain)."
  type        = string
  default     = ""
}

variable "app_settings" {
  description = <<-EOT
    Non-secret app settings, written to SSM as /<name>/env/<KEY> and passed to the
    container as environment variables, e.g. { COLLECT_LOCATIONS = "VA,MD" }.
    Put secrets in SSM by hand as SecureString under the same path instead (see infra/README.md).
  EOT
  type        = map(string)
  default     = {}

  validation {
    condition     = alltrue([for v in values(var.app_settings) : v != "" && !strcontains(v, "'")])
    error_message = "app_settings values must be non-empty and must not contain single quotes."
  }
}
