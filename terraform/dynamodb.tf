# DynamoDB = serverless key-value/document database. One table holds three kinds of item:
#
#   doc_id = "<document id>"          one per document: status, extraction result, and, while a
#                                     human review is pending, the Step Functions task token
#   doc_id = "COUNTER#YYYY-MM-DD"     the daily upload counter (expires itself via TTL)
#
# PAY_PER_REQUEST = no capacity to manage; at demo volume this costs cents.
resource "aws_dynamodb_table" "documents" {
  name         = "${var.project}-documents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "doc_id"

  attribute {
    name = "doc_id"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }
  attribute {
    name = "created_at"
    type = "S"
  }

  # Global secondary index = a second way to look items up. The review app queries
  # status = "pending_review" to list documents waiting for a person. Items without a
  # status (the counters) are simply not in the index.
  global_secondary_index {
    name = "status-index"
    key_schema {
      attribute_name = "status"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "created_at"
      key_type       = "RANGE"
    }
    projection_type = "ALL"
  }

  # Items with an "expires_at" epoch timestamp are deleted automatically (used by the counters).
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}
