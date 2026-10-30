import re
from difflib import SequenceMatcher

_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\\left", ""),
    ("\\right", ""),
    ("\\dfrac", "\\frac"),
    ("\\tfrac", "\\frac"),
    ("\\cdot", "*"),
    ("\\times", "*"),
    ("\\div", ":"),
    ("\\le", "<="),
    ("\\ge", ">="),
    ("\\leq", "<="),
    ("\\geq", ">="),
    ("\\ne", "!="),
    ("\\neq", "!="),
    ("\\displaystyle", ""),
    ("\\,", ""),
    ("\\;", ""),
    ("\\!", ""),
    ("\\quad", ""),
    ("−", "-"),
    ("–", "-"),
    ("×", "*"),
    ("·", "*"),
    ("≤", "<="),
    ("≥", ">="),
    ("≠", "!="),
    ("х", "x"),
    ("у", "y"),
    ("²", "^2"),
    ("³", "^3"),
    (",", "."),
)
_ORDERED = tuple(sorted(_REPLACEMENTS, key=lambda item: -len(item[0])))
_SPACES = re.compile(r"\s+")
_COMMAND = re.compile(r"\\([a-zA-Z]+)")
_FRAC = re.compile(r"\\frac\{([^{}]*)\}\{([^{}]*)\}")
_SQRT = re.compile(r"\\sqrt\{([^{}]*)\}")
_SINGLE_BRACE = re.compile(r"\{([^{}]?)\}")


def _clean(value: str) -> str:
    text = value.strip().strip("$").strip()
    for source, target in _ORDERED:
        text = text.replace(source, target)
    return _SPACES.sub("", text)


def _unbrace(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _SINGLE_BRACE.sub(r"\1", text)
    return text


def normalize_latex(value: str) -> str:
    return _unbrace(_clean(value)).rstrip(".")


def latex_to_plain(value: str) -> str:
    text = _clean(value)
    previous = None
    while previous != text:
        previous = text
        text = _FRAC.sub(r"(\1)/(\2)", text)
        text = _SQRT.sub(r"sqrt(\1)", text)
    text = _unbrace(_COMMAND.sub(r"\1", text))
    text = text.replace("{", "(").replace("}", ")").replace("^", "")
    return text.rstrip(".").lower()


def plain(value: str) -> str:
    return _clean(value).replace("^", "").rstrip(".").lower()


def similarity(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()
