from __future__ import annotations

import ast
import operator
from collections.abc import Callable


MAX_EXPRESSION_LENGTH = 240
MAX_ABS_INPUT = 10**120
MAX_RESULT_DIGITS = 2000
MAX_POWER_EXPONENT = 100_000


ALLOWED_BINARY_OPERATORS: dict[
    type[ast.operator], Callable[[float | int, float | int], float | int]
] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
ALLOWED_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float | int], float | int]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def safe_eval(expression: str) -> float | int:
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"表达式过长，最多 {MAX_EXPRESSION_LENGTH} 个字符")
    node = ast.parse(expression, mode="eval")
    result = _eval_node(node.body)
    _ensure_result_size(result)
    return result


def _eval_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        _ensure_input_size(node.value)
        return node.value

    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_BINARY_OPERATORS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow):
            _ensure_power_size(left, right)
        result = ALLOWED_BINARY_OPERATORS[type(node.op)](left, right)
        _ensure_result_size(result)
        return result

    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_UNARY_OPERATORS:
        result = ALLOWED_UNARY_OPERATORS[type(node.op)](_eval_node(node.operand))
        _ensure_result_size(result)
        return result

    raise ValueError("只支持数字和 + - * / // % ** ()")


def _ensure_input_size(value: float | int) -> None:
    if isinstance(value, int) and abs(value) > MAX_ABS_INPUT:
        raise ValueError("输入数字过大")


def _ensure_power_size(base: float | int, exponent: float | int) -> None:
    if not isinstance(exponent, int):
        if abs(exponent) > 1000:
            raise ValueError("指数过大")
        return

    if exponent < 0:
        if abs(exponent) > 1000:
            raise ValueError("负指数过大")
        return

    if exponent > MAX_POWER_EXPONENT:
        raise ValueError(f"指数过大，最多 {MAX_POWER_EXPONENT}")

    if isinstance(base, int):
        estimated_digits = _decimal_digits(base) * max(exponent, 1)
        if estimated_digits > MAX_RESULT_DIGITS:
            raise ValueError(f"结果过大，最多输出约 {MAX_RESULT_DIGITS} 位")


def _ensure_result_size(value: float | int) -> None:
    if isinstance(value, int) and _decimal_digits(value) > MAX_RESULT_DIGITS:
        raise ValueError(f"结果过大，最多输出 {MAX_RESULT_DIGITS} 位")


def _decimal_digits(value: int) -> int:
    value = abs(value)
    if value < 10:
        return 1
    return len(str(value))
