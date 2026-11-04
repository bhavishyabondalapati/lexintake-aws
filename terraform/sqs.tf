# SQS = message queue. This one is the dead-letter queue (DLQ): when a workflow step fails after
# its retries, the state machine drops the document id, the step and the error here, so
# nothing disappears silently.
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.project}-dlq"
  message_retention_seconds = 1209600 # 14 days, the maximum
  sqs_managed_sse_enabled   = true
}
