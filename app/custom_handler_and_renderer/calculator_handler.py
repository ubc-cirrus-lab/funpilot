"""
Custom Calculator Handler

This is an example custom toolcall handler that evaluates a math expression string
and stores the result in the workflow state.

This file is uploaded to the FunPilot registry via:
  funpilot handler register -n calculator -c calculator_handler.py

Contract:
  The file must define a function called `execute(state, **kwargs)` that
  receives the current workflow state dict and returns it (possibly modified).

Handler params (passed via workflow definition's handler_params):
  - expression (str): A math expression to evaluate, e.g. "1 + 2 + 3"

State fields written:
  - _handler_state["calculator_result"]: The numeric result of the expression
  - _handler_state["calculator_expression"]: The original expression string
"""

import ast
import operator

# Supported operators for safe evaluation
_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    """Safely evaluate an AST node containing only arithmetic operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value)}")
    elif isinstance(node, ast.BinOp):
        op_func = _OPERATORS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return op_func(left, right)
    elif isinstance(node, ast.UnaryOp):
        op_func = _OPERATORS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_func(_safe_eval(node.operand))
    else:
        raise ValueError(f"Unsupported AST node: {type(node).__name__}")


def execute(state, **kwargs):
    """Execute the calculator handler.

    Evaluates a math expression safely (no exec/eval of arbitrary code)
    and stores the result in _handler_state for downstream nodes.

    Args:
        state: The current workflow AgentState dict.
        **kwargs: Must contain 'expression' (str).

    Returns:
        The modified state dict.
    """
    expression = kwargs.get("expression", "0")

    try:
        # Parse the expression into an AST and evaluate safely
        tree = ast.parse(str(expression), mode="eval")
        result = _safe_eval(tree)

        # Store result in _handler_state for cross-node persistence
        handler_state = state.get("_handler_state") or {}
        handler_state["calculator_result"] = result
        handler_state["calculator_expression"] = str(expression)
        state["_handler_state"] = handler_state

    except Exception as exc:
        state["llm_error"] = f"Calculator handler failed: {exc}"
        handler_state = state.get("_handler_state") or {}
        handler_state["calculator_result"] = 0
        handler_state["calculator_expression"] = str(expression)
        state["_handler_state"] = handler_state

    return state
