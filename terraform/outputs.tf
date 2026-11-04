output "bucket_name" {
  value = aws_s3_bucket.docs.bucket
}

output "documents_table" {
  value = aws_dynamodb_table.documents.name
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "anthropic_key_parameter" {
  value = aws_ssm_parameter.anthropic_api_key.name
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}

output "review_app_url" {
  description = "Open this in a browser (only from the IP you deployed from)."
  value       = "http://${aws_instance.review.public_ip}:8000"
}
