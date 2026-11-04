"""The model call, behind an `Extractor` interface so tests can swap in a fake and never touch the
API. (Adapted from LexIntake's AnthropicExtractor.)

- Prompt caching: the system prompt carries a cache marker, so repeat calls read it from the
  cache at a fraction of the price.
- Retries: the SDK itself retries dropped connections, 408/409/429 and 5xx a couple of times. What
  still fails is raised as TransientError (the state machine retries with backoff) or
  PermanentError (it goes to the dead-letter queue).
- A refusal, a cut-off answer or an answer that fails validation is NOT an exception: it is
  recorded as the outcome, and the document goes to human review instead of burning more credit.
"""

import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from common.doctext import DocText
from common.errors import PermanentError, TransientError
from common.schemas import Extraction

MAX_TOKENS = 8_000
MAX_ERROR_CHARS = 1_000
FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")
RETRYABLE_STATUS = {408, 409, 429}


@dataclass
class LlmResponse:
    text: str
    stop_reason: str | None
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    request_id: str | None = None


class Extractor(Protocol):
    def complete(self, system: str, user: str, max_tokens: int) -> LlmResponse: ...


class AnthropicExtractor:
    def __init__(self, api_key: str, model: str, client=None) -> None:
        import anthropic

        self.anthropic = anthropic
        self.model = model
        self.client = client or anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=100.0)

    def complete(self, system: str, user: str, max_tokens: int) -> LlmResponse:
        a = self.anthropic
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            )
        except a.APIStatusError as e:
            message = f"{type(e).__name__} {e.status_code}: {e.message}"[:MAX_ERROR_CHARS]
            if e.status_code in RETRYABLE_STATUS or e.status_code >= 500:
                raise TransientError(message) from e
            raise PermanentError(message) from e
        except a.APIConnectionError as e:  # includes timeouts
            raise TransientError(f"{type(e).__name__}: {e}"[:MAX_ERROR_CHARS]) from e

        usage = response.usage
        return LlmResponse(
            text="".join(b.text for b in response.content if b.type == "text"),
            stop_reason=response.stop_reason,
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            request_id=getattr(response, "_request_id", None),
        )


def interpret(response: LlmResponse, doc: DocText) -> dict:
    """Model answer -> the JSON saved to S3. Never trusts the answer: it is parsed and validated,
    and anything unusable becomes an outcome other than "ok"."""
    result: dict = {
        "outcome": "ok",
        "model": response.model,
        "stop_reason": response.stop_reason,
        "request_id": response.request_id,
        "usage": {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cache_write_tokens": response.cache_write_tokens,
            "cache_read_tokens": response.cache_read_tokens,
        },
        "error": None,
        "classification": None,
        "fields": None,
    }
    if response.stop_reason == "refusal":
        return {**result, "outcome": "refused", "error": "the model declined to answer"}
    if response.stop_reason == "max_tokens":
        return {**result, "outcome": "invalid_output", "error": "output cut off at max_tokens"}
    try:
        parsed = Extraction.model_validate_json(
            FENCE.sub("", response.text), context={"page_count": doc.page_count}
        )
    except ValidationError as e:
        return {**result, "outcome": "invalid_output", "error": str(e)[:MAX_ERROR_CHARS]}

    result["classification"] = parsed.classification.model_dump(mode="json")
    if parsed.nda_fields is not None:
        result["fields"] = {
            name: cited.model_dump(mode="json") for name, cited in parsed.nda_fields.cited().items()
        }
    return result
