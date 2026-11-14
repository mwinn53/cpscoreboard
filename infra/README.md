# Infrastructure (AWS, us-east-1)

Terraform for the production stack: a single Graviton EC2 instance running Docker
Compose (the app plus Caddy for HTTPS), deployed from GitHub Actions.

```
GitHub push to master ─► Actions: tests ─► build arm64 image ─► ECR
                                           └─► SSM Run Command ─► EC2: docker compose pull && up -d
Browser ─► https://<site_hostname> (or <elastic-ip>.sslip.io) ─► Caddy (TLS) ─► app:8080
```

| Resource | Notes |
|---|---|
| EC2 `t4g.small`, Amazon Linux 2023 | No SSH; shell access via SSM Session Manager. IMDSv2 only. |
| Elastic IP | Stable address. The hostname is `<a-b-c-d>.sslip.io`, which resolves to that IP, so no domain is needed. |
| EBS `/data` volume (gp3, encrypted) | App database, season archive (`/data/archive`) and Caddy certificates. Separate from the instance and protected by `prevent_destroy`. |
| Daily snapshots (DLM) | Of the `/data` volume; keeps 7. |
| ECR repository | Keeps the 10 most recent images; scan on push. |
| CloudWatch Logs `/cpscoreboard` | Logs from the app and Caddy containers; kept 30 days. |
| SSM parameters `/cpscoreboard/env/*` | Become the container's environment variables on each deploy. |
| IAM | Instance role, plus a GitHub OIDC deploy role that only `master` of your repo can assume. |

Rough cost: **about $19/month** (instance ~$12, Elastic IP ~$3.60, EBS and snapshots ~$3).

## One-time setup

Prerequisites: [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.6,
the [AWS CLI](https://aws.amazon.com/cli/) signed in with admin rights to the account,
and the GitHub CLI (`gh auth login`).

```sh
cd infra
cp terraform.tfvars.example terraform.tfvars   # set github_repo and acme_email
terraform init
terraform apply
```

Then point GitHub Actions at the new stack. Terraform prints the exact commands:

```sh
terraform output -raw github_variables_commands   # run the 4 `gh variable set` lines it prints
```

These are repository **variables**, not secrets. None of them is sensitive, and
AWS access uses OIDC, so the repo stores no AWS keys.

Finally, deploy by merging to `master`, or run the **Deploy** workflow manually from
the Actions tab. The first deploy waits for the instance's first-boot setup, and
Caddy needs about 30 seconds to get the TLS certificate. Then open the site:

```sh
terraform output site_url
```

## Changing app settings

Non-secret settings go in `app_settings` in `terraform.tfvars`, followed by
`terraform apply`. **Secrets** (`ADMIN_BOOTSTRAP_TOKEN` now, X API keys in milestone 5) must never go
in Terraform, because they would be saved in the state file. Create them directly
instead:

```sh
aws ssm put-parameter --name /cpscoreboard/env/ADMIN_BOOTSTRAP_TOKEN --type SecureString --value '...'
```

Either way, the change takes effect on the next deploy. To apply it without
pushing code, re-run the latest **Deploy** workflow.

## Access restriction, custom hostname, email

- **`allowed_cidrs`** limits who can reach the site on 443; the default is public. **`http_cidrs`**
  does the same for port 80 and defaults to `allowed_cidrs`. While port 80 is restricted, certificates
  can't be issued or renewed. To keep the site private but let certificates work, set
  `http_cidrs = ["0.0.0.0/0"]`: port 80 only answers certificate checks and redirects to HTTPS.
- **`site_hostname`** adds a custom name, which needs an A record pointing at the Elastic IP. Caddy serves it
  alongside the sslip.io name.
- **`mail_domain` / `mail_sender`** create an SES domain identity (Easy DKIM, plus a custom MAIL FROM at
  `bounce.<domain>`) and let the instance send as that domain. `terraform output -raw dns_records_to_add`
  prints the records to add at your DNS host. SES stays in the sandbox (verified recipients only) until
  production access is granted.
- Deploys verify `/healthz` over HTTPS through Caddy **from the instance itself**, so they pass even
  when the site is IP-restricted.

## Operations

- **Shell on the server:** `aws ssm start-session --target $(terraform output -raw instance_id)`
  (requires the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)).
  The app lives in `/opt/cpscoreboard`, and its data is in `/data`.
- **Logs:** `aws logs tail /cpscoreboard --follow`
- **Replace the instance** (e.g. for a newer AMI): `terraform apply -replace=aws_instance.web`,
  then re-run Deploy. `/data` is reattached, and existing data is never reformatted.
- **Terraform state** is local (`infra/terraform.tfstate`, gitignored). Keep a
  backup until it moves to an S3 backend ([#23](https://github.com/mwinn53/cpscoreboard/issues/23)).
- **Season archive:** one gzipped full scoreboard per day in `/data/archive`, also
  downloadable from `/admin/archive`. It's covered by the daily `/data` snapshots.
- **Tearing down:** `terraform destroy` refuses to delete the data volume
  because of `prevent_destroy`. Remove that line first if you really mean it.

## Notes

- **TLS without a domain:** sslip.io hostnames are shared by everyone, so Let's
  Encrypt rate limits are possible. Caddy automatically falls back to ZeroSSL.
  With a real domain, set `site_hostname` and point an A record at the Elastic IP;
  production uses `cpscores.savannahrivertech.com`.
- **ARM:** the instance is Graviton (arm64). The image is built natively on
  GitHub's `ubuntu-24.04-arm` runners, which are free for public repos.
- **Already have GitHub's OIDC provider** in this account? Set
  `create_github_oidc_provider = false`.
