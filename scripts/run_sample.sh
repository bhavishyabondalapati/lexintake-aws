#!/usr/bin/env bash
# Uploads a PDF to the deployed pipeline and waits until it is decided or waiting for review.
# Usage: scripts/run_sample.sh [file.pdf]     (AWS credentials must be in the environment)
set -euo pipefail
cd "$(dirname "$0")/.."

FILE="${1:-samples/sample_nda.pdf}"
BUCKET=$(terraform -chdir=terraform output -raw bucket_name)
TABLE=$(terraform -chdir=terraform output -raw documents_table)
DOC_ID=$(uuidgen | tr 'A-Z' 'a-z')

aws s3 cp "$FILE" "s3://$BUCKET/uploads/$DOC_ID/$(basename "$FILE")" --only-show-errors
echo "uploaded $FILE as doc_id=$DOC_ID"

KEY="{\"doc_id\":{\"S\":\"$DOC_ID\"}}"

for _ in $(seq 1 60); do
  STATUS=$(aws dynamodb get-item --table-name "$TABLE" --key "$KEY" \
    --query 'Item.status.S' --output text 2>/dev/null || true)
  case "$STATUS" in
    auto_approved|pending_review|approved|rejected|failed|expired)
      echo "status: $STATUS"
      # Never print the task token.
      aws dynamodb get-item --table-name "$TABLE" --key "$KEY" --output json \
        --query 'Item.{status:status.S,doc_type:doc_type.S,confidence:confidence.N,risk:risk.S,reasons:reasons.S,error:error.S,input_tokens:input_tokens.N,output_tokens:output_tokens.N}'
      if [ "$STATUS" = "pending_review" ]; then
        echo "resolve it with: make review DOC=$DOC_ID ACTION=approve   (or ACTION=reject)"
      fi
      exit 0 ;;
  esac
  sleep 3
done
echo "not decided after 3 minutes (last status: ${STATUS:-none}); check the Step Functions console"
exit 1
