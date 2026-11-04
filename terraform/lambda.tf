# Lambda = run a function on demand, pay per millisecond. Four functions (python3.12, x86_64):
#   parse, extract, score = the pipeline steps
#   review_request        = stores the Step Functions task token in DynamoDB (see its docstring)
#
# `make build` creates build/<function>/ (code + packages); Terraform zips each folder.

locals {
  functions = ["parse", "extract", "score", "review_request"]
}

data "archive_file" "lambda" {
  for_each         = toset(local.functions)
  type             = "zip"
  source_dir       = "${path.module}/../build/${each.key}"
  output_path      = "${path.module}/../build/${each.key}.zip"
  output_file_mode = "0644"
}

# Keep logs 14 days so they don't pile up.
resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = toset(local.functions)
  name              = "/aws/lambda/${var.project}-${each.key}"
  retention_in_days = 14
}

resource "aws_lambda_function" "parse" {
  function_name    = "${var.project}-parse"
  role             = aws_iam_role.lambda["parse"].arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "handler.handler"
  filename         = data.archive_file.lambda["parse"].output_path
  source_code_hash = data.archive_file.lambda["parse"].output_base64sha256
  timeout          = 60
  memory_size      = 512

  environment {
    variables = {
      MAX_UPLOAD_BYTES = tostring(var.max_upload_mb * 1024 * 1024)
      MAX_PAGES        = "40"
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "extract" {
  function_name    = "${var.project}-extract"
  role             = aws_iam_role.lambda["extract"].arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "handler.handler"
  filename         = data.archive_file.lambda["extract"].output_path
  source_code_hash = data.archive_file.lambda["extract"].output_base64sha256
  timeout          = 120 # the API call itself times out at 100s
  memory_size      = 512

  environment {
    variables = {
      MODEL             = var.anthropic_model
      API_KEY_PARAMETER = aws_ssm_parameter.anthropic_api_key.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "score" {
  function_name    = "${var.project}-score"
  role             = aws_iam_role.lambda["score"].arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "handler.handler"
  filename         = data.archive_file.lambda["score"].output_path
  source_code_hash = data.archive_file.lambda["score"].output_base64sha256
  timeout          = 30
  memory_size      = 256

  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "review_request" {
  function_name    = "${var.project}-review-request"
  role             = aws_iam_role.lambda["review_request"].arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "handler.handler"
  filename         = data.archive_file.lambda["review_request"].output_path
  source_code_hash = data.archive_file.lambda["review_request"].output_base64sha256
  timeout          = 15
  memory_size      = 128

  environment {
    variables = {
      TABLE = aws_dynamodb_table.documents.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}
