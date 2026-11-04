"""Step 2: extract. One Anthropic API call that classifies the document and, for an NDA, extracts
its fields with quotes. The validated answer is saved to S3 as results/<doc_id>/extraction.json.

If the document has no text the model is not called at all (no point paying for an empty prompt).

Event:   {"doc_id", "bucket", "parsed_key"}
Returns: {"extraction_key", "outcome", "input_tokens", "output_tokens"}
"""

import json
import os

import boto3

from common import llm, prompts
from common.doctext import DocText

_s3 = None
_extractor: llm.Extractor | None = None


def s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def get_extractor() -> llm.Extractor:
    """Built on first use, so the API key is read from SSM once per warm Lambda, not per call.
    The key is only ever in memory: never in an environment variable, a file or the logs."""
    global _extractor
    if _extractor is None:
        ssm = boto3.client("ssm")
        key = ssm.get_parameter(Name=os.environ["API_KEY_PARAMETER"], WithDecryption=True)[
            "Parameter"
        ]["Value"]
        _extractor = llm.AnthropicExtractor(api_key=key, model=os.environ["MODEL"])
    return _extractor


def handler(event, context=None):
    s3 = s3_client()
    bucket, doc_id = event["bucket"], event["doc_id"]
    doc = DocText.from_json(
        json.loads(s3.get_object(Bucket=bucket, Key=event["parsed_key"])["Body"].read())
    )

    if not doc.norm_text:
        result = {"outcome": "no_text", "error": None, "classification": None, "fields": None}
        result["usage"] = {"input_tokens": 0, "output_tokens": 0}
    else:
        response = get_extractor().complete(
            prompts.system_prompt(), prompts.user_prompt(doc), llm.MAX_TOKENS
        )
        result = llm.interpret(response, doc)
        result["prompt_version"] = prompts.PROMPT_VERSION

    extraction_key = f"results/{doc_id}/extraction.json"
    s3.put_object(
        Bucket=bucket,
        Key=extraction_key,
        Body=json.dumps(result).encode(),
        ContentType="application/json",
    )
    return {
        "extraction_key": extraction_key,
        "outcome": result["outcome"],
        "input_tokens": result["usage"]["input_tokens"],
        "output_tokens": result["usage"]["output_tokens"],
    }
