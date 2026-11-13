"""Ask an LLM for a pydantic object, with fallbacks (used by intake AND plan generation).

Models and providers differ in how well they return structured data, so we try 3 ways,
from most to least reliable:
  1. with_structured_output(method="json_schema")   - provider enforces our JSON schema
  2. with_structured_output(method="function_calling") - schema sent as a "tool"
  3. plain text + "reply with JSON" instructions, then we cut out the first {...} block
     and validate it with pydantic ourselves.
"""
import json
import logging
import re
from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """None of the 3 ways produced a valid object."""


def parse_first_json(text: str) -> dict:
    """Find the first {...} block in a reply (models like to add text or ``` around JSON)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in: {text[:200]!r}")
    return json.loads(match.group(0))


def message_text(message) -> str:
    """Text content of an LLM reply (some providers return a list of content parts)."""
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content)


def invoke_structured(llm: BaseChatModel, prompt_messages: list[BaseMessage], schema: type[T]) -> T:
    """Return a `schema` object from the LLM, trying the 3 methods above in order."""
    errors = []
    for method in ("json_schema", "function_calling"):
        try:
            result = llm.with_structured_output(schema, method=method).invoke(prompt_messages)
            if isinstance(result, dict):
                result = schema.model_validate(result)
            if isinstance(result, schema):
                return result
            raise ValueError(f"Unexpected result: {result!r}")
        except Exception as e:  # not supported by this model/provider, or invalid output
            logger.warning("Structured output with %s failed: %s", method, e)
            errors.append(f"{method}: {e}")

    # Last try: plain text with format instructions added as one more message.
    parser = PydanticOutputParser(pydantic_object=schema)
    messages = list(prompt_messages) + [HumanMessage(content=parser.get_format_instructions())]
    try:
        raw = message_text(llm.invoke(messages))
        return schema.model_validate(parse_first_json(raw))
    except Exception as e:
        errors.append(f"raw_json: {e}")
        raise StructuredOutputError("; ".join(errors)) from e
