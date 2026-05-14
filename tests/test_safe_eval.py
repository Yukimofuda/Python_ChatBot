from src.chatbot.safe_math import safe_eval


def test_safe_eval_arithmetic() -> None:
    assert safe_eval("1 + 2 * (3 + 4)") == 15


def test_safe_eval_rejects_calls() -> None:
    try:
        safe_eval("__import__('os').system('echo unsafe')")
    except ValueError:
        return
    raise AssertionError("safe_eval should reject function calls")
