"""Prompt-intent evaluation harness for the Tender Optimization Assistant.

This package drives the *real* Bedrock tool-use loop with natural-language
prompts and scores whether the assistant:

  1. routes to the right tool(s),
  2. with the right scope / arguments, and
  3. produces a final answer that matches the user's intent

against a fixed, fully-documented data fixture. It is the iterate-until-it-
matches-intent companion to the offline adversarial suites in ``tests/``.

See ``harness.py`` for the runner and ``cases.py`` for the intent cases.
"""
