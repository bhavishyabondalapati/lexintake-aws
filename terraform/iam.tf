# IAM = who may do what. Every Lambda gets its own role (least privilege): it can touch only the
# S3 prefixes, table, parameter and log group that function actually needs.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  for_each           = toset(local.functions)
  name               = "${var.project}-${each.key}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Writing logs: only to the function's own log group.
data "aws_iam_policy_document" "logs" {
  for_each = toset(local.functions)
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda[each.key].arn}:*"]
  }
}

resource "aws_iam_role_policy" "logs" {
  for_each = toset(local.functions)
  name     = "logs"
  role     = aws_iam_role.lambda[each.key].id
  policy   = data.aws_iam_policy_document.logs[each.key].json
}

# parse: read uploaded PDFs, write parsed text.
data "aws_iam_policy_document" "parse" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.docs.arn}/uploads/*"]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.docs.arn}/parsed/*"]
  }
}

resource "aws_iam_role_policy" "parse" {
  name   = "parse"
  role   = aws_iam_role.lambda["parse"].id
  policy = data.aws_iam_policy_document.parse.json
}

# extract: read parsed text, write the model's answer, read the API key.
data "aws_iam_policy_document" "extract" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.docs.arn}/parsed/*"]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.docs.arn}/results/*"]
  }
  statement {
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.anthropic_api_key.arn]
  }
}

resource "aws_iam_role_policy" "extract" {
  name   = "extract"
  role   = aws_iam_role.lambda["extract"].id
  policy = data.aws_iam_policy_document.extract.json
}

# score: read parsed text and the model's answer, write the score.
data "aws_iam_policy_document" "score" {
  statement {
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.docs.arn}/parsed/*",
      "${aws_s3_bucket.docs.arn}/results/*",
    ]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.docs.arn}/results/*"]
  }
}

resource "aws_iam_role_policy" "score" {
  name   = "score"
  role   = aws_iam_role.lambda["score"].id
  policy = data.aws_iam_policy_document.score.json
}

# review_request: update one item in the documents table.
data "aws_iam_policy_document" "review_request" {
  statement {
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.documents.arn]
  }
}

resource "aws_iam_role_policy" "review_request" {
  name   = "review-request"
  role   = aws_iam_role.lambda["review_request"].id
  policy = data.aws_iam_policy_document.review_request.json
}

# --- Step Functions: invoke the four Lambdas, update the table, send to the DLQ ---

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${var.project}-state-machine"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

data "aws_iam_policy_document" "sfn" {
  statement {
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.parse.arn,
      aws_lambda_function.extract.arn,
      aws_lambda_function.score.arn,
      aws_lambda_function.review_request.arn,
    ]
  }
  statement {
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.documents.arn]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role_policy" "sfn" {
  name   = "pipeline"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

# --- EventBridge: may start this one state machine ---

data "aws_iam_policy_document" "events_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "events" {
  name               = "${var.project}-eventbridge-start"
  assume_role_policy = data.aws_iam_policy_document.events_assume.json
}

resource "aws_iam_role_policy" "events" {
  name = "start-pipeline"
  role = aws_iam_role.events.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = aws_sfn_state_machine.pipeline.arn
    }]
  })
}
