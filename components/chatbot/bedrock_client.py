"""
Amazon Bedrock client for the Tender Optimization assistant.

Talks to Claude (Anthropic) on Amazon Bedrock through the Converse API using
boto3. Credentials are loaded from an .env file (tests/.env or project .env):

- AWS_BEDROCK_API_KEY  -> exported as AWS_BEARER_TOKEN_BEDROCK (bearer-token auth)
- AWS_accessKeyId / AWS_secretAccessKey -> SigV4 fallback if no bearer token
- BEDROCK_MODEL_ID     -> e.g. us.anthropic.claude-opus-4-6-20251101-v1:0
- BEDROCK_REGION / AWS_REGION / S3_REGION -> region (defaults to us-east-1)

The Converse API is the Bedrock-native abstraction over Claude's Messages API
and supports tool use / function calling, which the assistant relies on.
"""
from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from typing import Callable, Iterator, Optional

logger = logging.getLogger(__name__)

# Default Claude-on-Bedrock inference profile (US cross-region). Overridable via env.
DEFAULT_MODEL_ID = "us.anthropic.claude-opus-4-8"
DEFAULT_REGION = "us-east-1"

# Some hand-written / stale BEDROCK_MODEL_ID values don't correspond to a real
# Bedrock inference profile and 400 with "model identifier is invalid". Map the
# known-bad forms to their valid profile so the assistant still works.
_MODEL_ID_FIXUPS = {
    "us.anthropic.claude-opus-4-6-20251101-v1:0": "us.anthropic.claude-opus-4-6-v1",
    "anthropic.claude-opus-4-6-20251101-v1:0": "us.anthropic.claude-opus-4-6-v1",
    "us.anthropic.claude-opus-4-6": "us.anthropic.claude-opus-4-6-v1",
}

_ENV_LOADED = False


def _load_env() -> None:
    """Load credentials from tests/.env or project .env exactly once.

    Maps AWS_BEDROCK_API_KEY -> AWS_BEARER_TOKEN_BEDROCK so botocore picks up the
    Bedrock bearer token automatically. Existing process env vars win, so a real
    AWS profile is never clobbered.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    try:
        from dotenv import load_dotenv
    except Exception:  # pragma: no cover - dotenv is a hard dep, but degrade gracefully
        load_dotenv = None

    root = Path(__file__).resolve().parents[2]
    for candidate in (root / "tests" / ".env", root / ".env"):
        if candidate.exists() and load_dotenv is not None:
            # Do not override anything already set in the real environment.
            load_dotenv(candidate, override=False)

    # Bedrock bearer token: botocore reads AWS_BEARER_TOKEN_BEDROCK.
    bearer = os.environ.get("AWS_BEDROCK_API_KEY")
    if bearer and not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = bearer.strip()

    # SigV4 fallback: the .env uses non-standard capitalization.
    if not os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_accessKeyId"):
        os.environ["AWS_ACCESS_KEY_ID"] = os.environ["AWS_accessKeyId"].strip()
    if not os.environ.get("AWS_SECRET_ACCESS_KEY") and os.environ.get("AWS_secretAccessKey"):
        os.environ["AWS_SECRET_ACCESS_KEY"] = os.environ["AWS_secretAccessKey"].strip()

    _ENV_LOADED = True


def _resolve_region() -> str:
    for key in ("BEDROCK_REGION", "AWS_REGION", "AWS_DEFAULT_REGION", "S3_REGION"):
        val = os.environ.get(key)
        if val and val.strip():
            return val.strip()
    return DEFAULT_REGION


def _resolve_model_id() -> str:
    val = os.environ.get("BEDROCK_MODEL_ID")
    model = val.strip() if val and val.strip() else DEFAULT_MODEL_ID
    fixed = _MODEL_ID_FIXUPS.get(model)
    if fixed:
        logger.info("Rewrote stale BEDROCK_MODEL_ID %s -> %s", model, fixed)
        return fixed
    return model


class BedrockClientError(RuntimeError):
    """Raised when the Bedrock client cannot be created or a call fails."""


class BedrockChatClient:
    """Thin wrapper around the Bedrock Converse API with tool-use support."""

    def __init__(self, model_id: Optional[str] = None, region: Optional[str] = None):
        _load_env()
        self.model_id = model_id or _resolve_model_id()
        self.region = region or _resolve_region()
        self._client = None
        self._use_sigv4 = False  # flips True if the bearer token is rejected

    @property
    def has_bearer_token(self) -> bool:
        _load_env()
        return bool(os.environ.get("AWS_BEARER_TOKEN_BEDROCK"))

    @property
    def has_sigv4(self) -> bool:
        _load_env()
        return bool(
            os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY")
        )

    @property
    def has_credentials(self) -> bool:
        return self.has_bearer_token or self.has_sigv4

    def _build_client(self, force_sigv4: bool):
        """Create a bedrock-runtime client.

        Bearer-token auth is automatic when AWS_BEARER_TOKEN_BEDROCK is set. When
        forcing SigV4 (bearer token rejected) we build the client with explicit
        access-key credentials and a v4-signing Config so botocore does not fall
        back to the (broken) bearer scheme at request time.
        """
        import boto3
        from botocore.config import Config

        if force_sigv4 and self.has_sigv4:
            return boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
                aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
                config=Config(signature_version="v4"),
            )
        return boto3.client("bedrock-runtime", region_name=self.region)

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise BedrockClientError(
                "boto3 is not installed. Run: pip install boto3"
            ) from e
        if not self.has_credentials:
            raise BedrockClientError(
                "No Bedrock credentials found. Set AWS_BEDROCK_API_KEY (or "
                "AWS_accessKeyId / AWS_secretAccessKey) in tests/.env."
            )
        try:
            self._client = self._build_client(force_sigv4=self._use_sigv4)
        except Exception as e:  # pragma: no cover
            raise BedrockClientError(f"Failed to create Bedrock client: {e}") from e
        return self._client

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        msg = str(exc)
        return (
            "AccessDeniedException" in msg
            or "Authentication failed" in msg
            or "UnrecognizedClientException" in msg
            or "security token" in msg.lower()
        )

    def converse(self, messages, system=None, tool_specs=None, max_tokens=4096):
        """Single Converse API call. Returns the raw response dict.

        If the Bedrock bearer token is rejected and SigV4 access keys are also
        available, transparently retries once via SigV4 so a stale API key in the
        .env doesn't take the whole assistant down.
        """
        # NOTE: no `temperature` — Opus 4.7+ (incl. opus-4-8) reject sampling
        # params and 400 with "`temperature` is deprecated for this model".
        kwargs = {
            "modelId": self.model_id,
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if system:
            kwargs["system"] = [{"text": system}] if isinstance(system, str) else system
        if tool_specs:
            kwargs["toolConfig"] = {"tools": tool_specs, "toolChoice": {"auto": {}}}

        try:
            return self._get_client().converse(**kwargs)
        except Exception as e:
            # Bearer token rejected but we have SigV4 keys -> retry via SigV4 once.
            if (
                self._is_auth_error(e)
                and not self._use_sigv4
                and self.has_bearer_token
                and self.has_sigv4
            ):
                logger.warning(
                    "Bedrock bearer token rejected; falling back to SigV4 access keys."
                )
                self._use_sigv4 = True
                self._client = None
                try:
                    return self._get_client().converse(**kwargs)
                except Exception as e2:
                    raise BedrockClientError(f"Bedrock Converse call failed: {e2}") from e2
            raise BedrockClientError(f"Bedrock Converse call failed: {e}") from e

    def converse_stream(self, messages, system=None, tool_specs=None, max_tokens=4096):
        """Streaming Converse API call. Returns the raw streaming response dict.

        The returned dict has a ``stream`` key whose value is an iterable of
        event dicts (``messageStart``, ``contentBlockStart``,
        ``contentBlockDelta``, ``contentBlockStop``, ``messageStop``,
        ``metadata``). Same auth/fallback behaviour as ``converse``: if the
        bearer token is rejected and SigV4 keys exist, retries once via SigV4.
        """
        kwargs = {
            "modelId": self.model_id,
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if system:
            kwargs["system"] = [{"text": system}] if isinstance(system, str) else system
        if tool_specs:
            kwargs["toolConfig"] = {"tools": tool_specs, "toolChoice": {"auto": {}}}

        try:
            return self._get_client().converse_stream(**kwargs)
        except Exception as e:
            if (
                self._is_auth_error(e)
                and not self._use_sigv4
                and self.has_bearer_token
                and self.has_sigv4
            ):
                logger.warning(
                    "Bedrock bearer token rejected; falling back to SigV4 access keys."
                )
                self._use_sigv4 = True
                self._client = None
                try:
                    return self._get_client().converse_stream(**kwargs)
                except Exception as e2:
                    raise BedrockClientError(
                        f"Bedrock ConverseStream call failed: {e2}"
                    ) from e2
            raise BedrockClientError(f"Bedrock ConverseStream call failed: {e}") from e

    @staticmethod
    def _assemble_streamed_message(stream) -> tuple:
        """Consume a Converse stream, yielding text deltas and rebuilding the turn.

        This is a generator: it yields each text fragment as it arrives (so the
        caller can render incrementally), then returns — via StopIteration.value
        — a ``(output_message, stop_reason)`` pair reconstructed from the event
        stream, in the same shape ``converse`` produces under
        ``response["output"]["message"]`` / ``response["stopReason"]``.

        Tool-use blocks arrive as a JSON string split across
        ``contentBlockDelta`` events; we accumulate the fragments per content
        block and parse them once the block stops.
        """
        # Per-content-block accumulators, keyed by contentBlockIndex.
        blocks: dict = {}
        order: list = []
        stop_reason = "end_turn"

        def _ensure(idx):
            if idx not in blocks:
                blocks[idx] = {"text": "", "tool_use": None, "tool_json": ""}
                order.append(idx)
            return blocks[idx]

        for event in stream:
            if "contentBlockStart" in event:
                start = event["contentBlockStart"]
                idx = start.get("contentBlockIndex", 0)
                blk = _ensure(idx)
                tool_use = start.get("start", {}).get("toolUse")
                if tool_use:
                    blk["tool_use"] = {
                        "toolUseId": tool_use.get("toolUseId"),
                        "name": tool_use.get("name"),
                    }
            elif "contentBlockDelta" in event:
                delta_evt = event["contentBlockDelta"]
                idx = delta_evt.get("contentBlockIndex", 0)
                blk = _ensure(idx)
                delta = delta_evt.get("delta", {})
                if "text" in delta:
                    text = delta["text"]
                    blk["text"] += text
                    yield text
                tool_delta = delta.get("toolUse")
                if tool_delta and "input" in tool_delta:
                    blk["tool_json"] += tool_delta["input"]
            elif "messageStop" in event:
                stop_reason = event["messageStop"].get("stopReason", stop_reason)
            # messageStart / contentBlockStop / metadata carry nothing we rebuild.

        content: list = []
        for idx in order:
            blk = blocks[idx]
            if blk["tool_use"] is not None:
                tool_json = blk["tool_json"].strip()
                try:
                    tool_input = json.loads(tool_json) if tool_json else {}
                except (ValueError, TypeError):
                    tool_input = {}
                content.append(
                    {"toolUse": {**blk["tool_use"], "input": tool_input}}
                )
            elif blk["text"]:
                content.append({"text": blk["text"]})

        output_message = {"role": "assistant", "content": content}
        return output_message, stop_reason

    def stream_conversation(
        self,
        messages: list,
        system: str,
        tool_specs: list,
        tool_executor: Callable[[str, dict], tuple],
        max_iterations: int = 6,
        max_tokens: int = 4096,
    ) -> Iterator[dict]:
        """Streaming agentic loop. Yields events as the model produces them.

        Same control flow as ``run_conversation`` — call the model, execute any
        tool calls, repeat — but the assistant's text is streamed out as it is
        generated. Yields event dicts:

          - {"type": "text", "text": <fragment>}      incremental assistant text
          - {"type": "tool_use", "name", "input"}      a tool is about to run
          - {"type": "tool_result", "name", "is_error", "input", "result"}
                                                       a tool finished (carries the
                                                       result so the UI can show it)
          - {"type": "done", "text", "messages", "tool_calls"}  final payload

        The terminal "done" event carries the same dict ``run_conversation``
        returns, so callers can use either API.
        """
        tool_calls: list[dict] = []

        for _ in range(max_iterations):
            response = self.converse_stream(messages, system, tool_specs, max_tokens)
            stream = response.get("stream")
            if stream is None:
                raise BedrockClientError("ConverseStream returned no stream.")

            # Drive the assembler generator, re-yielding its text fragments.
            assembler = self._assemble_streamed_message(stream)
            output_message = None
            stop_reason = "end_turn"
            try:
                while True:
                    fragment = next(assembler)
                    yield {"type": "text", "text": fragment}
            except StopIteration as stop:
                output_message, stop_reason = stop.value

            # Persist the assistant turn (including any toolUse blocks) verbatim.
            messages.append(output_message)
            content_blocks = output_message.get("content", [])

            if stop_reason != "tool_use":
                text = "".join(
                    b.get("text", "") for b in content_blocks if "text" in b
                ).strip()
                yield {
                    "type": "done",
                    "text": text,
                    "messages": messages,
                    "tool_calls": tool_calls,
                }
                return

            # Execute every requested tool and send all results back in one turn.
            tool_result_blocks = []
            for block in content_blocks:
                tool_use = block.get("toolUse")
                if not tool_use:
                    continue
                name = tool_use.get("name")
                tool_input = tool_use.get("input", {}) or {}
                yield {"type": "tool_use", "name": name, "input": tool_input}
                try:
                    result_obj, is_error = tool_executor(name, tool_input)
                except Exception as e:  # tool crashed — report back, don't die
                    result_obj, is_error = {"error": f"Tool '{name}' raised: {e}"}, True

                tool_calls.append(
                    {"name": name, "input": tool_input, "result": result_obj, "is_error": is_error}
                )
                yield {
                    "type": "tool_result",
                    "name": name,
                    "is_error": is_error,
                    "input": tool_input,
                    "result": result_obj,
                }
                tool_result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use.get("toolUseId"),
                            "content": [{"json": result_obj}],
                            "status": "error" if is_error else "success",
                        }
                    }
                )

            messages.append({"role": "user", "content": tool_result_blocks})

        # Exhausted iterations without a final answer.
        yield {
            "type": "done",
            "text": (
                "I reached the maximum number of tool steps without finishing. "
                "Please refine your request or try again."
            ),
            "messages": messages,
            "tool_calls": tool_calls,
        }

    def run_conversation(
        self,
        messages: list,
        system: str,
        tool_specs: list,
        tool_executor: Callable[[str, dict], tuple],
        max_iterations: int = 6,
        max_tokens: int = 4096,
    ):
        """Run an agentic loop: call the model, execute any tool calls, repeat.

        Args:
            messages: Converse-format message history (mutated in place / returned).
            system: System prompt string.
            tool_specs: Converse toolConfig tool specs.
            tool_executor: callable(name, input_dict) -> (result_obj, is_error: bool).
            max_iterations: hard cap on tool-call rounds (prevents infinite loops).

        Returns:
            dict with keys: text (final assistant text), messages (updated history),
            tool_calls (list of {name, input, result, is_error}).
        """
        tool_calls: list[dict] = []

        for _ in range(max_iterations):
            response = self.converse(messages, system, tool_specs, max_tokens)
            output_message = response.get("output", {}).get("message", {})
            # Persist the assistant turn (including any toolUse blocks) verbatim.
            messages.append(output_message)

            stop_reason = response.get("stopReason")
            content_blocks = output_message.get("content", [])

            if stop_reason != "tool_use":
                text = "".join(
                    b.get("text", "") for b in content_blocks if "text" in b
                ).strip()
                return {"text": text, "messages": messages, "tool_calls": tool_calls}

            # Execute every requested tool and send all results back in one turn.
            tool_result_blocks = []
            for block in content_blocks:
                tool_use = block.get("toolUse")
                if not tool_use:
                    continue
                name = tool_use.get("name")
                tool_input = tool_use.get("input", {}) or {}
                try:
                    result_obj, is_error = tool_executor(name, tool_input)
                except Exception as e:  # tool crashed — report back, don't die
                    result_obj, is_error = {"error": f"Tool '{name}' raised: {e}"}, True

                tool_calls.append(
                    {"name": name, "input": tool_input, "result": result_obj, "is_error": is_error}
                )
                tool_result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use.get("toolUseId"),
                            "content": [{"json": result_obj}],
                            "status": "error" if is_error else "success",
                        }
                    }
                )

            messages.append({"role": "user", "content": tool_result_blocks})

        # Exhausted iterations without a final answer.
        return {
            "text": (
                "I reached the maximum number of tool steps without finishing. "
                "Please refine your request or try again."
            ),
            "messages": messages,
            "tool_calls": tool_calls,
        }
