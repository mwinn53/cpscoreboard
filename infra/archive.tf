# --- Season archive copy (app/archive_s3.py): the daily raw boards, besides the EBS snapshots ---
# Private, versioned and encrypted. A day's object is replaced as the board changes that day;
# the replaced versions are kept for archive_noncurrent_days. Objects move to Glacier
# archive_glacier_days after upload, i.e. after the season.

resource "aws_s3_bucket" "archive" {
  bucket = "${var.name}-archive-${local.account_id}"
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "archive" {
  bucket = aws_s3_bucket.archive.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  bucket     = aws_s3_bucket.archive.id
  depends_on = [aws_s3_bucket_versioning.archive]

  rule {
    id     = "glacier-after-the-season"
    status = "Enabled"
    filter {
      # The daily files are ~70 KB; S3 skips transitioning objects under 128 KB unless asked.
      object_size_greater_than = 0
    }
    transition {
      days          = var.archive_glacier_days
      storage_class = "GLACIER"
    }
    noncurrent_version_expiration {
      noncurrent_days = var.archive_noncurrent_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "web_archive" {
  statement {
    sid       = "ListArchive"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.archive.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["archive/*"]
    }
  }

  statement {
    sid       = "CopyArchive"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.archive.arn}/archive/*"]
  }
}

resource "aws_iam_role_policy" "web_archive" {
  name   = "${var.name}-archive"
  role   = aws_iam_role.web.id
  policy = data.aws_iam_policy_document.web_archive.json
}
