resource "aws_s3_bucket" "web" {
  bucket        = "${local.name}-${local.account}-web"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_versioning" "web" {
  bucket = aws_s3_bucket.web.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    id     = "expire-old-frontend-versions"
    status = "Enabled"
    filter { prefix = "" }
    noncurrent_version_expiration { noncurrent_days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
  depends_on = [aws_s3_bucket_versioning.web]
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    {
      Effect    = "Allow", Principal = { Service = "cloudfront.amazonaws.com" },
      Action    = "s3:GetObject", Resource = "${aws_s3_bucket.web.arn}/*",
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } }
    },
    {
      Effect    = "Deny", Principal = "*", Action = "s3:*",
      Resource  = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"],
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }
  ] })
}

resource "aws_s3_object" "web" {
  for_each = {
    "index.html"    = "text/html; charset=utf-8"
    "dashboard.css" = "text/css; charset=utf-8"
    "dashboard.js"  = "application/javascript; charset=utf-8"
  }
  bucket                 = aws_s3_bucket.web.id
  key                    = each.key
  source                 = "${path.module}/../../../app/web/${each.key}"
  source_hash            = filesha256("${path.module}/../../../app/web/${each.key}")
  content_type           = each.value
  cache_control          = each.key == "index.html" ? "public, max-age=0, must-revalidate" : "public, max-age=60, must-revalidate"
  server_side_encryption = "AES256"
  depends_on             = [aws_s3_bucket_versioning.web, aws_s3_bucket_server_side_encryption_configuration.web]
}

resource "aws_s3_bucket" "data" {
  for_each      = toset(["lake", "queries"])
  bucket        = "${local.name}-${local.account}-${each.key}"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "data" {
  for_each                = aws_s3_bucket.data
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  rule {
    id     = "short-demo-retention"
    status = "Enabled"
    filter {
      prefix = ""
    }
    expiration {
      days = each.key == "lake" ? 14 : 7
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
  depends_on = [aws_s3_bucket_versioning.data]
}

resource "aws_s3_bucket_policy" "tls" {
  for_each = aws_s3_bucket.data
  bucket   = each.value.id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Deny", Principal = "*", Action = "s3:*", Resource = [each.value.arn, "${each.value.arn}/*"], Condition = {
        Bool = {
          "aws:SecureTransport" = "false"
        }
      }
      }
    ]
    }
  )
}
