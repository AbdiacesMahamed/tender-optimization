"""Bedrock connectivity preflight.

Read-only check that the configured credentials can reach Amazon Bedrock before
the assistant relies on them. Runs three steps in order, stopping at the first
failure with an actionable message:

  1. sts get-caller-identity      — who are the BASE credentials?
  2. sts assume-role (if BEDROCK_ROLE_ARN is set) — can we assume the role?
  3. Bedrock Converse 1-token ping — can we actually invoke the model?

Reuses BedrockChatClient's env loading and region/model/role resolution so this
mirrors exactly how the live app authenticates. Nothing here writes or mutates
any AWS resource.

Usage:
    python scripts/bedrock_preflight.py

Exit code 0 on success, 1 on the first failed step.
"""
import sys
from pathlib import Path

# Allow running as `python scripts/bedrock_preflight.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components.chatbot.bedrock_client import BedrockChatClient  # noqa: E402


def _ok(msg):
    print(f"  [OK]   {msg}")


def _fail(step, msg):
    print(f"  [FAIL] {msg}")
    print(f"\nPreflight stopped at: {step}")
    sys.exit(1)


def main():
    client = BedrockChatClient()
    region = client.region

    print("Bedrock preflight")
    print(f"  region   : {region}")
    print(f"  model    : {client.model_id}")
    print(
        "  auth     : "
        + (
            "assume-role" if client.has_role
            else "bearer-token" if client.has_bearer_token
            else "sigv4-keys" if client.has_sigv4
            else "NONE"
        )
    )
    print()

    if not client.has_credentials:
        _fail(
            "credential discovery",
            "No credentials found. Set BEDROCK_ROLE_ARN (preferred), "
            "AWS_BEDROCK_API_KEY, or AWS_accessKeyId/AWS_secretAccessKey in the "
            "project-root .env.",
        )

    import boto3
    from botocore.exceptions import ClientError, BotoCoreError

    # ---- Step 1: who are the base credentials? -------------------------------
    print("Step 1: sts get-caller-identity (base credentials)")
    try:
        ident = boto3.client("sts", region_name=region).get_caller_identity()
        _ok(f"Account {ident['Account']}  ARN {ident['Arn']}")
    except (ClientError, BotoCoreError) as e:
        _fail("sts get-caller-identity", f"{type(e).__name__}: {e}")

    # ---- Step 2: assume the role (only if configured) ------------------------
    role_arn = client.has_role
    print("\nStep 2: sts assume-role")
    if not role_arn:
        print("  [skip] BEDROCK_ROLE_ARN not set — using base credentials directly.")
    else:
        try:
            # Reuse the client's own assumption logic so this matches the app.
            creds = client._assume_role_credentials()
            assert creds is not None
            _ok("Assumed role; received temporary session credentials.")
        except (ClientError, BotoCoreError, AssertionError) as e:
            _fail(
                "sts assume-role",
                f"{type(e).__name__}: {e}\n"
                "  Check: the role's trust policy allows the base principal to "
                "sts:AssumeRole, and the base identity has sts:AssumeRole permission.",
            )

    # ---- Step 3: actually invoke the model -----------------------------------
    print("\nStep 3: Bedrock Converse ping (1 token)")
    try:
        resp = client.converse(
            messages=[{"role": "user", "content": [{"text": "ping"}]}],
            max_tokens=1,
        )
        usage = resp.get("usage", {})
        _ok(
            "Model responded. "
            f"tokens in/out = {usage.get('inputTokens', '?')}/{usage.get('outputTokens', '?')}"
        )
    except Exception as e:
        _fail(
            "Bedrock Converse",
            f"{type(e).__name__}: {e}\n"
            "  Check: the (assumed) identity has bedrock:InvokeModel on this model "
            f"profile, and the profile exists in region {region}.",
        )

    print("\nAll checks passed — Bedrock is reachable.")
    sys.exit(0)


if __name__ == "__main__":
    main()
