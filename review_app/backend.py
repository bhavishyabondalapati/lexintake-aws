"""Everything the review app does with AWS, in one class, so the web routes can be tested with a
fake. The EC2 instance's IAM role supplies the credentials: there are no access keys anywhere.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError


class ReviewError(Exception):
    """The decision could not be delivered (nothing waiting, or the wait already ended)."""


class AwsBackend:
    def __init__(self) -> None:
        self.region = os.environ["AWS_REGION"]
        self.bucket = os.environ["BUCKET"]
        self.table = boto3.resource("dynamodb", region_name=self.region).Table(os.environ["TABLE"])
        self.sfn = boto3.client("stepfunctions", region_name=self.region)
        # Regional endpoint + signature v4: a presigned POST to the global S3 endpoint would be
        # redirected for a non-us-east-1 bucket, and browsers don't follow that for uploads.
        self.s3 = boto3.client(
            "s3",
            region_name=self.region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )
        self.max_upload_bytes = int(os.environ["MAX_UPLOAD_BYTES"])
        self.daily_limit = int(os.environ["DAILY_DOC_LIMIT"])

    # --- uploads -----------------------------------------------------------------------------

    def reserve_upload(self) -> bool:
        """Count one document against today's limit. Atomic: two requests at the same moment
        cannot both take the last slot. Returns False when the limit is used up."""
        now = datetime.now(timezone.utc)
        expires = int((now + timedelta(days=3)).timestamp())  # the table's TTL removes it later
        try:
            self.table.update_item(
                Key={"doc_id": f"COUNTER#{now:%Y-%m-%d}"},
                UpdateExpression="ADD n :one SET expires_at = :exp",
                ConditionExpression="attribute_not_exists(n) OR n < :limit",
                ExpressionAttributeValues={":one": 1, ":limit": self.daily_limit, ":exp": expires},
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def presign_upload(self, doc_id: str, filename: str) -> dict:
        """A form S3 will accept from the browser: exactly this key, PDF only, at most the size
        cap. S3 itself enforces the size, so the check can't be skipped by editing the page."""
        return self.s3.generate_presigned_post(
            Bucket=self.bucket,
            Key=f"uploads/{doc_id}/{filename}",
            Fields={"Content-Type": "application/pdf"},
            Conditions=[
                {"Content-Type": "application/pdf"},
                ["content-length-range", 1, self.max_upload_bytes],
            ],
            ExpiresIn=300,
        )

    # --- documents ---------------------------------------------------------------------------

    def pending_reviews(self) -> list[dict]:
        response = self.table.query(
            IndexName="status-index",
            KeyConditionExpression=Key("status").eq("pending_review"),
            ScanIndexForward=False,
        )
        return [_public(item) for item in response["Items"]]

    def get_document(self, doc_id: str) -> dict | None:
        item = self.table.get_item(Key={"doc_id": doc_id}).get("Item")
        return _public(item) if item else None

    def get_score(self, score_key: str) -> dict | None:
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=score_key)["Body"].read()
        except ClientError:
            return None
        return json.loads(body)

    def pdf_url(self, key: str) -> str:
        return self.s3.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=300
        )

    # --- decisions ---------------------------------------------------------------------------

    def _token(self, doc_id: str) -> str:
        item = self.table.get_item(Key={"doc_id": doc_id}).get("Item") or {}
        token = item.get("task_token")
        if item.get("status") != "pending_review" or not token:
            raise ReviewError("This document is not waiting for review (already decided?).")
        return token

    def approve(self, doc_id: str) -> None:
        self._send(
            lambda token: self.sfn.send_task_success(
                taskToken=token, output=json.dumps({"decision": "approved", "at": time.time()})
            ),
            doc_id,
        )

    def reject(self, doc_id: str) -> None:
        self._send(
            lambda token: self.sfn.send_task_failure(
                taskToken=token, error="ReviewRejected", cause="rejected in the review app"
            ),
            doc_id,
        )

    def _send(self, call, doc_id: str) -> None:
        token = self._token(doc_id)
        try:
            call(token)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("TaskTimedOut", "TaskDoesNotExist", "InvalidToken"):
                raise ReviewError("The workflow is no longer waiting for this document.") from e
            raise


def _public(item: dict) -> dict:
    """A DynamoDB item for the templates. The task token is a credential for the workflow: it is
    never sent to the browser."""
    item = {k: v for k, v in item.items() if k != "task_token"}
    reasons = item.get("reasons")
    if isinstance(reasons, str):
        try:
            item["reasons"] = json.loads(reasons)
        except ValueError:
            item["reasons"] = [reasons]
    return item
