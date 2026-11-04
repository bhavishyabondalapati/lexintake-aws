#!/usr/bin/env bash
# Approve or reject a document that is waiting for human review, from the command line.
# This is what the review web app (Phase 3) does with the task token stored in DynamoDB.
# Usage: scripts/review.sh approve|reject <doc_id>
set -euo pipefail
cd "$(dirname "$0")/.."

ACTION="${1:?usage: review.sh approve|reject <doc_id>}"
DOC_ID="${2:?usage: review.sh approve|reject <doc_id>}"
TABLE=$(terraform -chdir=terraform output -raw documents_table)

TOKEN=$(aws dynamodb get-item --table-name "$TABLE" --key "{\"doc_id\":{\"S\":\"$DOC_ID\"}}" \
  --query 'Item.task_token.S' --output text)
if [ -z "$TOKEN" ] || [ "$TOKEN" = "None" ]; then
  echo "no task token for $DOC_ID: it is not waiting for review"
  exit 1
fi

case "$ACTION" in
  approve) aws stepfunctions send-task-success --task-token "$TOKEN" --task-output '{"decision":"approved"}' ;;
  reject) aws stepfunctions send-task-failure --task-token "$TOKEN" --error ReviewRejected --cause "rejected from the CLI" ;;
  *) echo "action must be approve or reject"; exit 1 ;;
esac
echo "$ACTION sent for $DOC_ID; the workflow finishes in a second or two"
