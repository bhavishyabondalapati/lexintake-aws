"""Step 3: score. Checks the model's answer against the document text and the NDA playbook, and
produces the three numbers the state machine's Choice state uses: confidence, risk and the number
of reasons for review. The full detail (every field check and playbook result) is saved to S3 as
results/<doc_id>/score.json for the review page.

No model call and no third-party packages except PyYAML (for the playbook file).

Event:   {"doc_id", "bucket", "parsed_key", "extraction_key"}
Returns: {"score_key", "doc_type", "confidence", "risk", "reason_count", "reasons"}
"""

import json
import os
from pathlib import Path

import boto3

from common.doctext import DocText
from common.playbook import load_playbook
from common.scoring import score_document

PLAYBOOK_PATH = Path(os.environ.get("PLAYBOOK_PATH", Path(__file__).parent / "nda_playbook.yaml"))

_s3 = None


def s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _read_json(bucket: str, key: str) -> dict:
    return json.loads(s3_client().get_object(Bucket=bucket, Key=key)["Body"].read())


def handler(event, context=None):
    bucket, doc_id = event["bucket"], event["doc_id"]
    doc = DocText.from_json(_read_json(bucket, event["parsed_key"]))
    extraction = _read_json(bucket, event["extraction_key"])

    result = score_document(doc, extraction, load_playbook(PLAYBOOK_PATH))
    result["usage"] = extraction.get("usage", {})
    result["model"] = extraction.get("model")

    score_key = f"results/{doc_id}/score.json"
    s3_client().put_object(
        Bucket=bucket,
        Key=score_key,
        Body=json.dumps(result).encode(),
        ContentType="application/json",
    )
    return {
        "score_key": score_key,
        "doc_type": result["doc_type"] or "unknown",
        "confidence": result["confidence"],
        "risk": result["risk"],
        "reason_count": result["reason_count"],
        # Short codes only ("code:field"): this goes through the state machine and into DynamoDB.
        "reasons": [
            r["code"] + (f":{r['field']}" if r["field"] else "") for r in result["reasons"]
        ],
    }
