"""Human review gate, part 1: store the task token.

The state machine calls this with .waitForTaskToken, which pauses the execution until someone calls
SendTaskSuccess / SendTaskFailure with the token. Step Functions cannot write that token to
DynamoDB itself (the callback pattern doesn't work with the DynamoDB integration), so this tiny
function does it. The review app later reads the token from the table.

Event: {"doc_id", "task_token"}   (the return value is ignored while the execution waits)
"""

import os
from datetime import datetime, timezone

import boto3

_table = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE"])
    return _table


def handler(event, context=None):
    table().update_item(
        Key={"doc_id": event["doc_id"]},
        UpdateExpression="SET #s = :s, task_token = :t, review_requested_at = :now",
        ConditionExpression="attribute_exists(doc_id)",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "pending_review",
            ":t": event["task_token"],
            ":now": datetime.now(timezone.utc).isoformat(),
        },
    )
