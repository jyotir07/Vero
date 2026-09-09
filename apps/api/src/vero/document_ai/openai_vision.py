"""Document extraction with OpenAI vision.

Used only for a real demo run; everything else uses the fake. The model is asked for a
strict JSON object and its answer is validated against the same required fields the
fake enforces, so a plausible-looking but wrong-shaped response fails extraction rather
than becoming a confident-looking number in a credit decision.
"""

import base64
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from openai import OpenAI

from vero.document_ai.base import (
    DEFAULT_CONFIDENCE,
    ExtractionFailed,
    ExtractionResult,
)
from vero.document_ai.fake import REQUIRED_FIELDS
from vero.domain.enums import DocumentType

PROMPT = """You are extracting structured data from a synthetic {document_type} used in
a technical demonstration. Return only a JSON object with these keys: {fields}, plus a
"confidence" between 0 and 1 reflecting how legible the document was. Amounts must be
integers in paise (1 rupee = 100 paise). If the document is unreadable or is not a
{document_type}, return {{"error": "reason"}}."""


class OpenAIVisionExtractor:
    def __init__(self, *, client: OpenAI, model: str, timeout: float = 30.0) -> None:
        self._client = client
        self._model = model
        self._timeout = timeout

    def extract(self, *, document_type: DocumentType, content: bytes) -> ExtractionResult:
        fields = ", ".join(REQUIRED_FIELDS[document_type])
        encoded = base64.b64encode(content).decode()

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                timeout=self._timeout,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": PROMPT.format(
                                    document_type=document_type.value, fields=fields
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:application/pdf;base64,{encoded}"},
                            },
                        ],
                    }
                ],
            )
        except Exception as exc:
            # Timeouts and transport errors are extraction failures, not crashes: the
            # workflow has a state for a document it could not read.
            raise ExtractionFailed(f"vision call failed: {exc}") from exc

        return self._parse(document_type, response.choices[0].message.content)

    @staticmethod
    def _parse(document_type: DocumentType, raw: str | None) -> ExtractionResult:
        if not raw:
            raise ExtractionFailed("model returned no content")
        try:
            payload: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExtractionFailed(f"model returned invalid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ExtractionFailed("model did not return an object")
        if "error" in payload:
            raise ExtractionFailed(str(payload["error"]))

        missing = [f for f in REQUIRED_FIELDS[document_type] if f not in payload]
        if missing:
            raise ExtractionFailed(f"missing fields for {document_type.value}: {missing}")

        raw_confidence = payload.pop("confidence", None)
        if raw_confidence is None:
            confidence = DEFAULT_CONFIDENCE
        else:
            try:
                confidence = Decimal(str(raw_confidence)).quantize(Decimal("0.001"))
            except InvalidOperation as exc:
                raise ExtractionFailed(f"confidence is not a number: {raw_confidence!r}") from exc

        return ExtractionResult(data=payload, confidence=confidence)
