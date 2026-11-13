# Outbound email (registration codes, milestone 4) via SES, from a domain whose DNS
# is hosted elsewhere: Terraform creates the identity and prints the DNS records to add.

locals {
  ses_enabled      = var.mail_domain != ""
  mail_from_domain = "${var.mail_from_subdomain}.${var.mail_domain}"
}

resource "aws_sesv2_email_identity" "domain" {
  count          = local.ses_enabled ? 1 : 0
  email_identity = var.mail_domain

  dkim_signing_attributes {
    next_signing_key_length = "RSA_2048_BIT"
  }
}

# Envelope sender (bounces) on a subdomain, so SPF aligns with the From domain under
# DMARC without touching the domain's existing SPF/MX records.
resource "aws_sesv2_email_identity_mail_from_attributes" "domain" {
  count                  = local.ses_enabled ? 1 : 0
  email_identity         = aws_sesv2_email_identity.domain[0].email_identity
  mail_from_domain       = local.mail_from_domain
  behavior_on_mx_failure = "USE_DEFAULT_VALUE"
}

data "aws_iam_policy_document" "ses_send" {
  count = local.ses_enabled ? 1 : 0

  statement {
    sid       = "SendFromOurDomain"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = [aws_sesv2_email_identity.domain[0].arn]
  }
}

resource "aws_iam_role_policy" "web_ses" {
  count  = local.ses_enabled ? 1 : 0
  name   = "${var.name}-ses-send"
  role   = aws_iam_role.web.id
  policy = data.aws_iam_policy_document.ses_send[0].json
}

output "dns_records_to_add" {
  description = "Add these at the domain's DNS host (names are relative to the domain)."
  value = !local.ses_enabled ? "SES not configured (mail_domain is empty)" : join("\n", concat(
    ["TYPE   NAME                                   VALUE"],
    [for t in aws_sesv2_email_identity.domain[0].dkim_signing_attributes[0].tokens :
    format("CNAME  %-38s %s", "${t}._domainkey", "${t}.dkim.amazonses.com")],
    [
      format("MX     %-38s %s", var.mail_from_subdomain, "10 feedback-smtp.${var.region}.amazonses.com"),
      format("TXT    %-38s %s", var.mail_from_subdomain, "v=spf1 include:amazonses.com ~all"),
    ],
    var.site_hostname == "" ? [] : [
      format("A      %-38s %s", trimsuffix(var.site_hostname, ".${var.mail_domain}"), aws_eip.web.public_ip),
    ],
  ))
}
