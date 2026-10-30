import re

_SUPERSCRIPT = dict(zip("0123456789+-=()nixyk", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱˣʸᵏ", strict=True))
_SUBSCRIPT = dict(zip("0123456789+-=()aeoxhklmnpst", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜ", strict=True))
_VULGAR = {
    ("1", "2"): "½",
    ("1", "3"): "⅓",
    ("2", "3"): "⅔",
    ("1", "4"): "¼",
    ("3", "4"): "¾",
    ("1", "5"): "⅕",
    ("1", "6"): "⅙",
    ("1", "8"): "⅛",
}
_SYMBOLS = {
    "cdot": "·",
    "times": "·",
    "div": ":",
    "le": "≤",
    "leq": "≤",
    "leqslant": "≤",
    "ge": "≥",
    "geq": "≥",
    "geqslant": "≥",
    "ne": "≠",
    "neq": "≠",
    "approx": "≈",
    "pm": "±",
    "mp": "∓",
    "infty": "∞",
    "in": "∈",
    "notin": "∉",
    "cup": "∪",
    "cap": "∩",
    "varnothing": "∅",
    "emptyset": "∅",
    "pi": "π",
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "varphi": "φ",
    "phi": "φ",
    "Rightarrow": "⇒",
    "Leftrightarrow": "⇔",
    "to": "→",
    "circ": "°",
    "lt": "<",
    "gt": ">",
    "lbrace": "{",
    "rbrace": "}",
    "{": "{",
    "}": "}",
    "%": "%",
    "angle": "∠",
    "perp": "⊥",
    "parallel": "∥",
    "triangle": "△",
}
_FUNCTIONS = {
    "sin": "sin",
    "cos": "cos",
    "tan": "tg",
    "tg": "tg",
    "cot": "ctg",
    "ctg": "ctg",
    "arcsin": "arcsin",
    "arccos": "arccos",
    "arctan": "arctg",
    "arctg": "arctg",
    "log": "log",
    "ln": "ln",
    "lg": "lg",
    "exp": "exp",
    "max": "max",
    "min": "min",
}
_SPACING = {",", ";", ":", "!", " ", "quad", "qquad", "displaystyle", "left", "right", "big", "Big"}
_TEXT_COMMANDS = {"text", "mathrm", "textrm", "textbf", "mathbf", "mbox", "operatorname", "mathit"}
_FRACTIONS = {"frac", "dfrac", "tfrac", "cfrac"}


def _read_group(text: str, index: int) -> tuple[str, int]:
    while index < len(text) and text[index] == " ":
        index += 1
    if index >= len(text):
        return "", index
    if text[index] == "{":
        depth = 0
        for position in range(index, len(text)):
            if text[position] == "{":
                depth += 1
            elif text[position] == "}":
                depth -= 1
                if depth == 0:
                    return text[index + 1 : position], position + 1
        return text[index + 1 :], len(text)
    if text[index] == "\\":
        match = re.match(r"\\([a-zA-Z]+|.)", text[index:])
        if match is not None:
            return match.group(0), index + match.end()
    return text[index], index + 1


def _is_simple(value: str) -> bool:
    return bool(
        re.fullmatch(r"[½⅓⅔¼¾⅕⅙⅛]|−?[0-9.,]+|[a-zA-Zα-ωπ]|[a-zA-Z][₀-₉]*|[0-9]*[a-zA-Zπ]", value)
    )


def _wrap(value: str) -> str:
    return value if _is_simple(value) or re.fullmatch(r"\(.*\)", value) else f"({value})"


def _script(value: str, table: dict[str, str], marker: str) -> str:
    plain = value.replace("−", "-").replace(" ", "")
    if plain and all(char in table for char in plain):
        return "".join(table[char] for char in plain)
    return f"{marker}{_wrap(value)}"


def _fraction(numerator: str, denominator: str) -> str:
    key = (numerator.strip(), denominator.strip())
    if key in _VULGAR:
        return _VULGAR[key]
    single = re.fullmatch(r"[0-9.,]+|[a-zA-Zπ][₀-₉]*|\(.*\)", denominator.strip())
    bottom = denominator.strip() if single else f"({denominator.strip()})"
    return f"{_wrap(numerator.strip())}/{bottom}"


def _root(radicand: str, degree: str | None) -> str:
    prefix = _script(degree, _SUPERSCRIPT, "") if degree else ""
    body = radicand if _is_simple(radicand) else f"({radicand})"
    return f"{prefix}√{body}"


def _command(text: str, index: int, name: str) -> tuple[str, int]:
    if name in _FRACTIONS:
        numerator, index = _read_group(text, index)
        denominator, index = _read_group(text, index)
        return _fraction(_convert(numerator), _convert(denominator)), index
    if name == "sqrt":
        degree = None
        if index < len(text) and text[index] == "[":
            end = text.find("]", index)
            degree, index = _convert(text[index + 1 : end]), end + 1
        radicand, index = _read_group(text, index)
        return _root(_convert(radicand), degree), index
    if name in _TEXT_COMMANDS:
        content, index = _read_group(text, index)
        return content if name != "operatorname" else _FUNCTIONS.get(content, content), index
    if name == "mathbb":
        content, index = _read_group(text, index)
        return {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ"}.get(content, content), index
    if name in ("begin", "end"):
        environment, index = _read_group(text, index)
        if name == "begin" and environment == "array":
            _, index = _read_group(text, index)
        if environment == "cases":
            return ("{ " if name == "begin" else " }"), index
        return "", index
    if name in _FUNCTIONS:
        return _FUNCTIONS[name] + " ", index
    if name in _SYMBOLS:
        return _SYMBOLS[name], index
    if name in _SPACING:
        if name in ("left", "right") and index < len(text) and text[index] == ".":
            index += 1
        return (" " if name in (",", ";", " ", "quad", "qquad") else ""), index
    if name == "\\":
        return "; ", index
    return name, index


def _convert(text: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            match = re.match(r"\\([a-zA-Z]+|.)", text[index:])
            name = match.group(1) if match is not None else ""
            converted, index = _command(text, index + (match.end() if match else 1), name)
            result.append(converted)
        elif char in "^_":
            group, index = _read_group(text, index + 1)
            value = _convert(group)
            if char == "^":
                result.append(_script(value, _SUPERSCRIPT, "^"))
            else:
                result.append(_script(value, _SUBSCRIPT, "_"))
        elif char == "{" or char == "}":
            index += 1
        elif char == "*":
            result.append("·")
            index += 1
        elif char == "-":
            result.append("−")
            index += 1
        else:
            result.append(char)
            index += 1
    return "".join(result)


_JOIN = re.compile(
    r"(?<![a-zA-Z])((?!(?:sin|cos|tg|ctg|log|ln|lg|arcsin|arccos|arctg|exp|max|min)\b)"
    r"[0-9a-zA-Z]+[⁰¹²³⁴⁵⁶⁷⁸⁹₀-₉]*) (?=[a-zA-Z(√])"
)


def _tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([=<>≤≥≠≈∈⇒])\s*", r" \1 ", text)
    text = re.sub(r"(?<=[\w)²³⁰¹⁴-⁹])\s*([+±])\s*", r" \1 ", text)
    text = re.sub(r"(?<=[\w)²³⁰¹⁴-⁹])\s*−\s*", " − ", text)
    text = re.sub(r"\s*·\s*", "·", text)
    text = re.sub(r"\s*∪\s*", " ∪ ", text)
    text = re.sub(r"\)\s+\(", ")(", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\s+([,;])", r"\1", text)
    text = re.sub(r" +(?=[₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹⁻ⁿ])", "", text)
    for _ in range(6):
        joined = _JOIN.sub(r"\1", text)
        if joined == text:
            break
        text = joined
    text = re.sub(r"(^|[(\[=<>≤≥≠;,]\s*)−\s+", r"\1−", text)
    return text.strip()


def to_display(latex: str) -> str:
    text = latex.strip().strip("$")
    return _tidy(_convert(text))
