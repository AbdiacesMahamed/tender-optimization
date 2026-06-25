"""
Amazon Bedrock client for the Tender Optimization assistant.

Talks to Claude (Anthropic) on Amazon Bedrock through the Converse API using
boto3. Credentials are loaded from the project-root .env file:

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
import time
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


def _json_sanitize(value):
    """Recursively scrub a tool result of anything Bedrock's Converse rejects.

    Two failure modes both surface as the SAME opaque ValidationException
    ("The format of the value at messages.N…toolResult…json is invalid") and
    both WEDGE the whole conversation, because the bad toolResult is persisted
    in the message history and re-sent on every later turn:

    1. Non-finite floats. ``json.dumps`` emits the bare tokens ``NaN`` /
       ``Infinity`` for these, which are not valid JSON. (e.g. a percent delta
       divided by a zero baseline.) -> replaced with ``None``.
    2. Empty-string object keys. Bedrock forbids ``""`` as a property name, so a
       result that buckets by a value that can be blank (e.g. a container with
       no assigned carrier SCAC, producing a ``carrier_mix[""]`` entry) poisons
       the session. -> the key is renamed to ``"(unassigned)"`` so the data is
       preserved rather than silently dropped. Whitespace-only keys are treated
       the same way.

    Also coerces numpy scalars (which expose ``.item()``) to native Python.
    Scrubbing at this boundary means no tool can ever wedge a conversation with
    a value it happened to produce on one edge-case input.
    """
    import math
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = k if (isinstance(k, str) and k.strip()) else (
                "(unassigned)" if isinstance(k, str) else k)
            out[key] = _json_sanitize(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_json_sanitize(v) for v in value]
    # numpy scalars expose .item(); fall back to the value untouched otherwise.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_sanitize(item())
        except Exception:
            return value
    return value


def _as_tool_result_json(result_obj):
    """Coerce a tool's return value into a clean JSON OBJECT for Converse.

    Bedrock's ``toolResult.content[0].json`` field requires a JSON object — a
    bare list, scalar, or ``None`` is rejected with a ValidationException, and
    because the offending toolResult is then persisted in the message history,
    EVERY subsequent turn in the conversation also 400s (the assistant wedges
    permanently). Most tools already return a dict, but the boundary must not
    depend on that: wrap any non-dict result, and deep-scrub non-finite floats,
    so neither a stray list/scalar nor a NaN can poison the session.
    """
    obj = result_obj if isinstance(result_obj, dict) else {"result": result_obj}
    return _json_sanitize(obj)

# Streamlit secret keys we know how to consume, mapped to the env var the rest
# of this module (and botocore) already reads. Keys may live at the top level of
# st.secrets or nested under an [aws] table — both are checked.
_SECRET_KEYS = (
    "AWS_BEDROCK_API_KEY",
    "AWS_accessKeyId",
    "AWS_secretAccessKey",
    "BEDROCK_MODEL_ID",
    "BEDROCK_REGION",
    "AWS_REGION",
    "S3_REGION",
)


def _load_streamlit_secrets() -> None:
    """Copy known credentials from st.secrets into os.environ (env wins).

    No-op when Streamlit is not installed or no secrets file exists, so local
    .env runs and unit tests are unaffected.
    """
    try:
        import streamlit as st
    except Exception:
        return

    try:
        secrets = st.secrets
    except Exception:
        # Accessing st.secrets with no secrets configured raises; that's fine.
        return

    # Support both flat keys and an [aws] section in secrets.toml.
    sources = [secrets]
    try:
        if "aws" in secrets:
            sources.append(secrets["aws"])
    except Exception:
        pass

    for src in sources:
        for key in _SECRET_KEYS:
            try:
                val = src.get(key)
            except Exception:
                val = None
            if val and not os.environ.get(key):
                os.environ[key] = str(val).strip()


def _load_env() -> None:
    """Load credentials from the project-root .env exactly once.

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
    # The .env lives at the project root. (tests/.env kept as a legacy fallback.)
    for candidate in (root / ".env", root / "tests" / ".env"):
        if candidate.exists() and load_dotenv is not None:
            # Do not override anything already set in the real environment.
            load_dotenv(candidate, override=False)

    # Streamlit Community Cloud: there is no .env file on the host. Credentials
    # live in the app's Secrets store (Settings -> Secrets), exposed as
    # st.secrets. Copy them into the environment so the resolution logic below
    # is identical to local .env runs. Existing env vars still win.
    _load_streamlit_secrets()

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
    def has_role(self) -> bool:
        _load_env()
        return bool(os.environ.get("BEDROCK_ROLE_ARN") and os.environ["BEDROCK_ROLE_ARN"].strip())

    @property
    def has_credentials(self) -> bool:
        return self.has_role or self.has_bearer_token or self.has_sigv4

    def _assume_role_credentials(self):
        """Assume BEDROCK_ROLE_ARN via STS and return temporary credentials.

        Returns a dict with aws_access_key_id / aws_secret_access_key /
        aws_session_token, or None when no role is configured. The base
        credentials used to call STS come from the default boto3 chain (env
        vars, shared config, instance profile), so the role can be assumed from
        the IAM user keys in the .env or from an ambient identity. Sessions are
        short-lived (the role caps duration at 1h), so the client is rebuilt per
        BedrockChatClient instance rather than cached process-wide.
        """
        role_arn = os.environ.get("BEDROCK_ROLE_ARN")
        if not role_arn or not role_arn.strip():
            return None
        import boto3

        session_name = os.environ.get("BEDROCK_ROLE_SESSION_NAME", "tender-optimization-bedrock")
        sts = boto3.client("sts", region_name=self.region)
        resp = sts.assume_role(RoleArn=role_arn.strip(), RoleSessionName=session_name)
        creds = resp["Credentials"]
        return {
            "aws_access_key_id": creds["AccessKeyId"],
            "aws_secret_access_key": creds["SecretAccessKey"],
            "aws_session_token": creds["SessionToken"],
        }

    def _build_client(self, force_sigv4: bool):
        """Create a bedrock-runtime client.

        Auth precedence:
        1. BEDROCK_ROLE_ARN set -> assume the role via STS and use the temporary
           credentials (SigV4). This is the preferred path: short-lived creds.
        2. Bearer-token auth is automatic when AWS_BEARER_TOKEN_BEDROCK is set
           (and we're not forcing SigV4).
        3. force_sigv4 with static access keys -> explicit v4-signed client so
           botocore does not fall back to the (broken) bearer scheme.
        """
        import boto3
        from botocore.config import Config

        assumed = self._assume_role_credentials()
        if assumed is not None:
            return boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                config=Config(signature_version="v4"),
                **assumed,
            )

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
                "AWS_accessKeyId / AWS_secretAccessKey) in the project-root .env."
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
          - {"type": "reasoning", "text"}              the model's thinking emitted
                                                       just before it called tools
                                                       this round (its rationale for
                                                       the calls that follow)
          - {"type": "tool_use", "name", "input"}      a tool is about to run
          - {"type": "tool_result", "name", "is_error", "input", "result",
             "duration_ms"}                            a tool finished (carries the
                                                       result so the UI can show it,
                                                       and how long it took)
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

            # The model usually narrates its plan in a text block BEFORE the
            # toolUse blocks in the same turn ("I'll first check the rate sheet…").
            # That is the assistant's reasoning for the tool calls about to run —
            # surface it as a discrete event so the UI/log can attribute it to the
            # tools that follow, rather than letting it blur into the final answer.
            reasoning = "".join(
                b.get("text", "") for b in content_blocks if "text" in b
            ).strip()
            if reasoning:
                yield {"type": "reasoning", "text": reasoning}

            # Execute every requested tool and send all results back in one turn.
            tool_result_blocks = []
            for block in content_blocks:
                tool_use = block.get("toolUse")
                if not tool_use:
                    continue
                name = tool_use.get("name")
                tool_input = tool_use.get("input", {}) or {}
                yield {"type": "tool_use", "name": name, "input": tool_input}
                started = time.perf_counter()
                try:
                    result_obj, is_error = tool_executor(name, tool_input)
                except Exception as e:  # tool crashed — report back, don't die
                    result_obj, is_error = {"error": f"Tool '{name}' raised: {e}"}, True
                duration_ms = round((time.perf_counter() - started) * 1000, 1)

                tool_calls.append(
                    {"name": name, "input": tool_input, "result": result_obj,
                     "is_error": is_error, "duration_ms": duration_ms,
                     "reasoning": reasoning}
                )
                yield {
                    "type": "tool_result",
                    "name": name,
                    "is_error": is_error,
                    "input": tool_input,
                    "result": result_obj,
                    "duration_ms": duration_ms,
                    "reasoning": reasoning,
                }
                tool_result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use.get("toolUseId"),
                            "content": [{"json": _as_tool_result_json(result_obj)}],
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

            # The model's pre-tool narration is its reasoning for the calls below.
            reasoning = "".join(
                b.get("text", "") for b in content_blocks if "text" in b
            ).strip()

            # Execute every requested tool and send all results back in one turn.
            tool_result_blocks = []
            for block in content_blocks:
                tool_use = block.get("toolUse")
                if not tool_use:
                    continue
                name = tool_use.get("name")
                tool_input = tool_use.get("input", {}) or {}
                started = time.perf_counter()
                try:
                    result_obj, is_error = tool_executor(name, tool_input)
                except Exception as e:  # tool crashed — report back, don't die
                    result_obj, is_error = {"error": f"Tool '{name}' raised: {e}"}, True
                duration_ms = round((time.perf_counter() - started) * 1000, 1)

                tool_calls.append(
                    {"name": name, "input": tool_input, "result": result_obj,
                     "is_error": is_error, "duration_ms": duration_ms,
                     "reasoning": reasoning}
                )
                tool_result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use.get("toolUseId"),
                            "content": [{"json": _as_tool_result_json(result_obj)}],
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
