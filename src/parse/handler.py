"""Step 1: parse. Reads the uploaded PDF from S3, extracts the text page by page and saves it to
S3 as parsed/<doc_id>.json (the next steps read it from there: Step Functions passes at most 256 KB
between states, and a contract can be longer).

Event:   {"doc_id", "bucket", "key", ...}
Returns: {"parsed_key", "page_count", "char_count", "partial"}
"""

import json
import os

import boto3

from common.errors import PermanentError
from common.pdf import parse_pdf

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
MAX_PAGES = int(os.environ.get("MAX_PAGES", 40))

_s3 = None


def s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def handler(event, context=None):
    s3 = s3_client()
    bucket, key, doc_id = event["bucket"], event["key"], event["doc_id"]

    head = s3.head_object(Bucket=bucket, Key=key)
    if head["ContentLength"] > MAX_UPLOAD_BYTES:
        raise PermanentError(
            f"file is {head['ContentLength']} bytes; the limit is {MAX_UPLOAD_BYTES}"
        )
    data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()

    doc = parse_pdf(data, max_pages=MAX_PAGES)

    parsed_key = f"parsed/{doc_id}.json"
    s3.put_object(
        Bucket=bucket,
        Key=parsed_key,
        Body=json.dumps(doc.to_json()).encode(),
        ContentType="application/json",
    )
    return {
        "parsed_key": parsed_key,
        "page_count": doc.page_count,
        "char_count": len(doc.norm_text),
        "partial": doc.partial,
    }
