# Step Functions = a workflow engine. The state machine (statemachine/pipeline.asl.json.tftpl)
# calls the Lambdas in order, retries failures with backoff, and can pause for days waiting for a
# person. "Standard" workflows keep a full execution history and can run up to a year.
resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.project}-pipeline"
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/../statemachine/pipeline.asl.json.tftpl", {
    table_name         = aws_dynamodb_table.documents.name
    dlq_url            = aws_sqs_queue.dlq.url
    parse_arn          = aws_lambda_function.parse.arn
    extract_arn        = aws_lambda_function.extract.arn
    score_arn          = aws_lambda_function.score.arn
    review_request_arn = aws_lambda_function.review_request.arn
  })
}

# EventBridge = event router. S3 publishes "Object Created" events to it (see s3.tf); this rule
# picks the ones under uploads/ in our bucket and starts one workflow execution per file.
resource "aws_cloudwatch_event_rule" "upload" {
  name        = "${var.project}-upload"
  description = "New file under uploads/ -> start the pipeline"

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.docs.bucket] }
      object = { key = [{ prefix = "uploads/" }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "pipeline" {
  rule     = aws_cloudwatch_event_rule.upload.name
  arn      = aws_sfn_state_machine.pipeline.arn
  role_arn = aws_iam_role.events.arn

  # Only pass what the workflow needs: {"bucket": ..., "key": ...}
  input_transformer {
    input_paths = {
      bucket = "$.detail.bucket.name"
      key    = "$.detail.object.key"
    }
    input_template = "{\"bucket\": <bucket>, \"key\": <key>}"
  }

  # If EventBridge can't start the workflow, keep the event instead of losing it.
  dead_letter_config {
    arn = aws_sqs_queue.dlq.arn
  }
}
