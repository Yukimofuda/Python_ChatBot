from src.chatbot.safe_math import safe_eval


def test_safe_eval_arithmetic() -> None:
    assert safe_eval("1 + 2 * (3 + 4)") == 15


def test_safe_eval_rejects_calls() -> None:
    try:
        safe_eval("__import__('os').system('echo unsafe')")
    except ValueError:
        return
    raise AssertionError("safe_eval should reject function calls")


def test_safe_eval_allows_larger_power_when_result_is_bounded() -> None:
    assert safe_eval("2 ** 100") == 1267650600228229401496703205376


def test_safe_eval_rejects_huge_result() -> None:
    try:
        safe_eval("0xfffffffffffffffffffff ** 0xfffffffffffffffffffff")
    except ValueError:
        return
    raise AssertionError("safe_eval should reject extremely large results")
