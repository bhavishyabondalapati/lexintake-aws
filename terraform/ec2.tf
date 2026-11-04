# EC2 = a virtual machine. One t3.micro runs the review web app (FastAPI, as a systemd service).
# It sits in the account's default VPC (the network AWS creates for you) with a public IP, and only
# your IP address may reach port 8000.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

# AWS publishes the id of the latest Amazon Linux 2023 image as a public SSM parameter.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# Security group = a firewall. Inbound: port 8000 from your IP only. No SSH at all (use SSM
# Session Manager if you need a shell). Outbound: open, so the instance can reach S3, DynamoDB
# and the package repositories.
resource "aws_security_group" "review" {
  name        = "${var.project}-review-app"
  description = "Review app: port 8000 from one IP"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Review app from my IP"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.my_ip_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Instance role = the identity the app runs as. The app gets temporary credentials from it
# automatically, so there are no access keys on the machine.
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "review" {
  name               = "${var.project}-review-app"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "review" {
  # list pending reviews, read one document, count uploads against the daily limit
  statement {
    actions = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"]
    resources = [
      aws_dynamodb_table.documents.arn,
      "${aws_dynamodb_table.documents.arn}/index/status-index",
    ]
  }
  # Presigned upload forms are signed with these permissions, so PutObject on uploads/ only.
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.docs.arn}/uploads/*"]
  }
  statement {
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.docs.arn}/uploads/*",
      "${aws_s3_bucket.docs.arn}/results/*",
      "${aws_s3_bucket.docs.arn}/app/*",
    ]
  }
  # Resume or fail a paused workflow. These two actions do not support resource-level
  # permissions (the task token is the credential), so the resource has to be "*".
  statement {
    actions   = ["states:SendTaskSuccess", "states:SendTaskFailure"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "review" {
  name   = "review-app"
  role   = aws_iam_role.review.id
  policy = data.aws_iam_policy_document.review.json
}

# Lets you open a shell on the instance with Session Manager instead of SSH keys.
resource "aws_iam_role_policy_attachment" "review_ssm" {
  role       = aws_iam_role.review.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "review" {
  name = "${var.project}-review-app"
  role = aws_iam_role.review.name
}

# The app's code is zipped and put in S3; the instance downloads it when it first boots.
data "archive_file" "review_app" {
  type             = "zip"
  source_dir       = "${path.module}/../review_app"
  output_path      = "${path.module}/../build/review_app.zip"
  output_file_mode = "0644"
  excludes         = ["__pycache__"]
}

resource "aws_s3_object" "review_app" {
  bucket = aws_s3_bucket.docs.id
  key    = "app/review_app.zip"
  source = data.archive_file.review_app.output_path
  etag   = data.archive_file.review_app.output_md5
}

resource "aws_instance" "review" {
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = "t3.micro"
  subnet_id                   = sort(data.aws_subnets.default.ids)[0]
  vpc_security_group_ids      = [aws_security_group.review.id]
  iam_instance_profile        = aws_iam_instance_profile.review.name
  associate_public_ip_address = true

  # IMDSv2 only: the instance metadata service (where role credentials come from) requires a
  # session token, which blocks a class of request-forgery attacks.
  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
    encrypted   = true
  }

  # Runs once at first boot. A new app version changes the hash inside it, which replaces the
  # instance (and its public IP) so the new code is installed from scratch.
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    region           = var.region
    bucket           = aws_s3_bucket.docs.id
    app_key          = aws_s3_object.review_app.key
    app_hash         = data.archive_file.review_app.output_md5
    table            = aws_dynamodb_table.documents.name
    max_upload_bytes = var.max_upload_mb * 1024 * 1024
    daily_doc_limit  = var.daily_doc_limit
  })
  user_data_replace_on_change = true

  tags = {
    Name = "${var.project}-review-app"
  }

  depends_on = [aws_iam_role_policy.review, aws_s3_object.review_app]
}
