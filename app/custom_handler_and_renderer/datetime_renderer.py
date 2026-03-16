"""
Custom DateTime Renderer

This is an example custom placeholder renderer that replaces {{.CustomPlaceHolderExample}}
in prompt templates with the current date and time string.

This file is uploaded to the FunPilot registry via:
  funpilot renderer register -n datetime_renderer -p CustomPlaceHolderExample \\
    -c datetime_renderer.py

Contract:
  The file must define a function called `render(*, context_data, state)` that
  returns a string. This string replaces the placeholder in the prompt template.

Arguments:
  - context_data: A ContextData object (or dict) with service metadata,
    metrics, alert rules, etc.
  - state: The current AgentState dict (or None if not in a workflow context).

Returns:
  A string that will be substituted for {{.CustomPlaceHolderExample}} in
  the prompt template.
"""

from datetime import datetime, timezone


def render(*, context_data=None, state=None):
    """Return the current UTC date and time as a human-readable string.

    Also includes the calculator result from _handler_state if available,
    demonstrating how renderers can read cross-node state set by handlers.
    """
    now = datetime.now(timezone.utc)
    parts = [f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"]

    # Optionally include calculator result if a calculator handler ran before
    if state and isinstance(state, dict):
        handler_state = state.get("_handler_state") or {}
        calc_result = handler_state.get("calculator_result")
        calc_expr = handler_state.get("calculator_expression")
        if calc_result is not None:
            parts.append(f"Calculator result: {calc_expr} = {calc_result}")

    return "\n".join(parts)
