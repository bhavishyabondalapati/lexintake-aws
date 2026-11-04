# S3 = object storage. Uploaded documents land under the uploads/ prefix.

resource "aws_s3_bucket" "docs" {
  bucket = local.bucket_name

  # Lets `make destroy` delete the bucket even when it still holds documents.
  force_destroy = true
}

# Nothing in this bucket is ever public.
resource "aws_s3_bucket_public_access_block" "docs" {
  bucket                  = aws_s3_bucket.docs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Demo uploads are deleted after 30 days so storage stays at ~$0.
resource "aws_s3_bucket_lifecycle_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id

  rule {
    id     = "expire-uploads"
    status = "Enabled"
    filter {
      prefix = "uploads/"
    }
    expiration {
      days = 30
    }
  }
}

# Send every S3 event to EventBridge. An EventBridge rule (Phase 2) filters for new
# objects under uploads/ and starts the Step Functions workflow.
resource "aws_s3_bucket_notification" "docs" {
  bucket      = aws_s3_bucket.docs.id
  eventbridge = true
}

# The review page uploads straight from the browser to S3 with a presigned POST, which is a
# cross-origin request. Anyone can POST only if they hold a presigned form, and that form
# enforces the max file size and the exact key, so allowing any origin is safe.
resource "aws_s3_bucket_cors_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id

  cors_rule {
    allowed_methods = ["POST"]
    allowed_origins = ["*"]
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}
