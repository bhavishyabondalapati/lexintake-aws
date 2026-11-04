# SQS = message queue. This one is the dead-letter queue (DLQ): when a workflow step fails after
# its retries, the state machine drops the document id, the step and the error here, so
# nothing disappears silently.
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.project}-dlq"
  message_retention_seconds = 1209600 # 14 days, the maximum
  sqs_managed_sse_enabled   = true
}

# Lets EventBridge drop an event here if it cannot start the workflow (for example it was
# throttled). Only the one rule defined in stepfunctions.tf may send.
resource "aws_sqs_queue_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowEventBridgeRule"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.dlq.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.upload.arn } }
    }]
  })
}
