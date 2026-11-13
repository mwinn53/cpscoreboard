output "site_url" {
  value = "https://${local.site_address}"
}

output "instance_id" {
  value = aws_instance.web.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}

output "github_variables_commands" {
  description = "Run these once to point the GitHub Actions deploy workflow at this stack."
  value       = <<-EOT
    gh variable set AWS_DEPLOY_ROLE_ARN --repo ${var.github_repo} --body "${aws_iam_role.github_deploy.arn}"
    gh variable set ECR_REPOSITORY_URL --repo ${var.github_repo} --body "${aws_ecr_repository.app.repository_url}"
    gh variable set EC2_INSTANCE_ID --repo ${var.github_repo} --body "${aws_instance.web.id}"
    gh variable set SITE_URL --repo ${var.github_repo} --body "https://${local.site_address}"
  EOT
}
