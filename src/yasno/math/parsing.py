import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any

import sympy as sp
from latex2sympy2_extended import latex2sympy
from sympy.parsing.sympy_parser import (
    auto_number,
    auto_symbol,
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
)

from yasno.math.limits import (
    MAX_DEGREE,
    MAX_EXPONENT_BITS,
    MAX_INPUT_LENGTH,
    MAX_INTEGER_DIGITS,
    MAX_NODES,
    MathTimeout,
    reraise_if_expired,
    time_limit,
)


class Op(StrEnum):
    EQ = "="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="


INEQUALITY_OPS = frozenset({Op.LT, Op.LE, Op.GT, Op.GE})
FLIPPED = {Op.LT: Op.GT, Op.GT: Op.LT, Op.LE: Op.GE, Op.GE: Op.LE, Op.EQ: Op.EQ, Op.NE: Op.NE}


class NoteKind(StrEnum):
    DOMAIN = "domain"
    REJECT = "reject"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class Expression:
    expr: Any
    raw: Any
    continuation: bool = False
    label: str = ""


@dataclass(frozen=True, slots=True)
class Equation:
    lhs: Any
    rhs: Any
    raw_lhs: Any
    raw_rhs: Any


@dataclass(frozen=True, slots=True)
class Inequality:
    parts: tuple[Any, ...]
    ops: tuple[Op, ...]
    raw: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class Chain:
    parts: tuple[Any, ...]
    ops: tuple[Op, ...]
    raw: tuple[Any, ...]
    continuation: bool = False


@dataclass(frozen=True, slots=True)
class Answer:
    variable: Any
    values: Any
    points: tuple[tuple[Any, ...], ...] = ()
    variables: tuple[Any, ...] = ()
    explicit: bool = False


@dataclass(frozen=True, slots=True)
class System:
    members: tuple[Equation | Inequality, ...]


@dataclass(frozen=True, slots=True)
class Disjunction:
    members: tuple[Equation | Inequality, ...]


@dataclass(frozen=True, slots=True)
class Note:
    kind: NoteKind
    inner: "Statement | None" = None


@dataclass(frozen=True, slots=True)
class Unparseable:
    reason: str


type Statement = (
    Expression | Equation | Inequality | Chain | Answer | System | Disjunction | Note | Unparseable
)


class ParseRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def relational(lhs: Any, op: Op, rhs: Any) -> Any:
    match op:
        case Op.EQ:
            return sp.Eq(lhs, rhs, evaluate=False)
        case Op.NE:
            return sp.Ne(lhs, rhs, evaluate=False)
        case Op.LT:
            return sp.Lt(lhs, rhs, evaluate=False)
        case Op.LE:
            return sp.Le(lhs, rhs, evaluate=False)
        case Op.GT:
            return sp.Gt(lhs, rhs, evaluate=False)
        case Op.GE:
            return sp.Ge(lhs, rhs, evaluate=False)


_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_CHAR_REPLACEMENTS = (
    ("\u00a0", " "),
    ("−", "-"),
    ("–", "-"),
    ("—", "-"),
    ("≈", "="),
    ("‒", "-"),
    ("×", r" \cdot "),
    ("·", r" \cdot "),
    ("⋅", r" \cdot "),
    ("∙", r" \cdot "),
    ("•", r" \cdot "),
    ("÷", "/"),
    ("≤", "<="),
    ("⩽", "<="),
    ("≥", ">="),
    ("⩾", ">="),
    ("≠", "!="),
    ("∞", r" \infty "),
    ("π", r" \pi "),
    ("∈", r" \in "),
    ("⋃", "∪"),
    ("Ø", "∅"),
    ("√", r" \sqrt "),
    ("∛", r" \sqrt[3] "),
    ("⟹", "⇒"),
    ("→", "⇒"),
    ("⇔", "⇒"),
    ("⟺", "⇒"),
    ("ℝ", " ℝ "),
    ("’", "'"),
    ("′", "'"),
    ("½", "(1/2)"),
    ("⅓", "(1/3)"),
    ("¼", "(1/4)"),
    ("¾", "(3/4)"),
    ("⅔", "(2/3)"),
    ("$", " "),
)
_LATEX_REPLACEMENTS = (
    (re.compile(r"\\(?:left|right)\s*\."), ""),
    (
        re.compile(
            r"\\(?:left|right|bigl|bigr|Bigl|Bigr|big|Big|biggl|biggr|bigg|Bigg)(?![a-zA-Z])"
        ),
        "",
    ),
    (re.compile(r"\\(?:displaystyle|limits|nolimits)(?![a-zA-Z])"), ""),
    (re.compile(r"\\[()\[\]]"), " "),
    (re.compile(r"\\[dtc]frac(?![a-zA-Z])"), r"\\frac"),
    (re.compile(r"\\frac\s*(\d)\s*(\d)"), r"\\frac{\1}{\2}"),
    (re.compile(r"\\(?:leqslant|leq|le)(?![a-zA-Z])"), "<="),
    (re.compile(r"\\(?:geqslant|geq|ge)(?![a-zA-Z])"), ">="),
    (re.compile(r"\\(?:neq|ne)(?![a-zA-Z])"), "!="),
    (re.compile(r"\\lt(?![a-zA-Z])"), "<"),
    (re.compile(r"\\gt(?![a-zA-Z])"), ">"),
    (
        re.compile(
            r"\\(?:Longrightarrow|Rightarrow|implies|Longleftrightarrow|Leftrightarrow|iff"
            r"|rightarrow|to)(?![a-zA-Z])"
        ),
        "⇒",
    ),
    (re.compile(r"=>"), "⇒"),
    (re.compile(r"\\approx(?![a-zA-Z])"), "="),
    (re.compile(r"\s\|\s*(?:[-+:/]|\\cdot)[^|=<>]*$"), ""),
    (re.compile(r"\\cup(?![a-zA-Z])"), "∪"),
    (re.compile(r"\\(?:varnothing|emptyset|O)(?![a-zA-Z])"), "∅"),
    (re.compile(r"\\(?:times|ast|bullet|cdotp)(?![a-zA-Z])"), r"\\cdot "),
    (re.compile(r"\\div(?![a-zA-Z])"), "/"),
    (re.compile(r"\\(?:pm|mp)(?![a-zA-Z])"), "±"),
    (re.compile(r"\\q?quad(?![a-zA-Z])"), " ; "),
    (re.compile(r"\\[,;:! ]"), " "),
    (re.compile(r"~"), " "),
    (re.compile(r"\\mathbb\s*\{\s*R\s*\}"), " ℝ "),
    (
        re.compile(
            r"\\(?:operatorname|mathrm|textrm|textbf|textit|text|mathbf|mathit|mbox)\s*"
            r"\{([^{}]*)\}"
        ),
        r" \1 ",
    ),
    (re.compile(r"\\(?:tg|operatorname\{tg\})(?![a-zA-Z])"), r"\\tan "),
    (re.compile(r"\\ctg(?![a-zA-Z])"), r"\\cot "),
    (re.compile(r"\\arctg(?![a-zA-Z])"), r"\\arctan "),
    (re.compile(r"\\lg(?![a-zA-Z])"), r"\\log_{10} "),
)
_PLAIN_FUNCTIONS = re.compile(
    r"(?<![\\a-zA-Z])(arctg|arcsin|arccos|arctan|ctg|tg|sin|cos|tan|cot|ln|lg|log|exp|sqrt)"
)
_FUNCTION_LATEX = {
    "arctg": r"\arctan ",
    "arctan": r"\arctan ",
    "arcsin": r"\arcsin ",
    "arccos": r"\arccos ",
    "ctg": r"\cot ",
    "tg": r"\tan ",
    "sin": r"\sin ",
    "cos": r"\cos ",
    "tan": r"\tan ",
    "cot": r"\cot ",
    "ln": r"\ln ",
    "lg": r"\log_{10} ",
    "log": r"\log",
    "exp": r"\exp ",
    "sqrt": r"\sqrt",
}
_CYRILLIC = re.compile(r"[А-Яа-яЁё]+\.?")
_ANSWER_PREFIX = re.compile(r"^\s*(?:ответ|отв)\s*[:.\-]?\s*", re.IGNORECASE)
_DOMAIN_PREFIX = re.compile(
    r"^\s*(?:о\.?\s*д\.?\s*з\.?|область\s+допустимых\s+значений)\s*[:.\-]?\s*", re.IGNORECASE
)
_NUMBERING = re.compile(r"^\s*(?:\d{1,2}|[а-яa-z])\)\s+", re.IGNORECASE)
_REJECT = re.compile(
    r"посторонн|не\s+удовлетвор|не\s+входит|не\s+подходит|не\s+принадлежит|не\s+является\s+корн"
    r"|не\s+уд\.|исключ",
    re.IGNORECASE,
)
_EMPTY = re.compile(
    r"(?:корней\s+нет|нет\s+корней|решений\s+нет|нет\s+решений|не\s+имеет\s+(?:действительных\s+)?"
    r"(?:корней|решений)|(?:корней|решений)\s+не\s+имеет|пустое\s+множество)",
    re.IGNORECASE,
)
_ALL = re.compile(
    r"(?:любое\s+(?:действительное\s+)?число|любое|любой|все\s+(?:действительные\s+)?числа"
    r"|бесконечно\s+много)",
    re.IGNORECASE,
)
_OR = re.compile(r"(?<![А-Яа-яЁё])или(?![А-Яа-яЁё])", re.IGNORECASE)
_AND = re.compile(r"(?<![А-Яа-яЁё])и(?![А-Яа-яЁё])", re.IGNORECASE)
_CASES = re.compile(
    r"\\begin\s*\{(cases|array|aligned|gathered|matrix)\}(?:\s*\{[^{}]*\})?(.*?)\\end\s*\{\1\}",
    re.DOTALL,
)
_DERIVATIVE_LABEL = re.compile(
    r"^\s*([fgyhs])\s*(?P<prime>'+|\^\s*\{?\s*\\prime\s*\}?)?\s*(?:\(\s*[a-z]\s*\))?\s*=(?!=)"
)
_KEYWORDS = frozenset(
    {
        "lambda",
        "import",
        "exec",
        "eval",
        "open",
        "def",
        "class",
        "for",
        "while",
        "if",
        "else",
        "not",
        "and",
        "or",
        "is",
        "in",
        "from",
        "with",
        "yield",
        "return",
        "global",
        "del",
        "pass",
        "raise",
        "try",
        "assert",
        "async",
        "await",
        "nonlocal",
        "none",
        "true",
        "false",
        "print",
        "compile",
        "getattr",
        "setattr",
        "globals",
        "locals",
        "vars",
        "dir",
        "type",
        "object",
    }
)
_DANGEROUS = frozenset(
    {"lambda", "import", "exec", "eval", "open", "compile", "getattr", "globals", "locals"}
)
_PLAIN_ALLOWED = re.compile(r"^[0-9a-zA-Z_+\-*/^()., ]+$")
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
_ALLOWED_FUNCTIONS = (
    sp.log,
    sp.exp,
    sp.sin,
    sp.cos,
    sp.tan,
    sp.cot,
    sp.asin,
    sp.acos,
    sp.atan,
    sp.acot,
    sp.Abs,
)
_SYMBOL_NAME = re.compile(r"^[a-zA-Z]{1,6}(?:_\{?[a-zA-Z0-9,]{1,4}\}?)?$")


def _lg(value: Any) -> Any:
    return sp.log(value, 10)


_PLAIN_GLOBALS: dict[str, Any] = {
    "__builtins__": {},
    "Integer": sp.Integer,
    "Float": sp.Float,
    "Rational": sp.Rational,
    "Symbol": sp.Symbol,
    "Add": sp.Add,
    "Mul": sp.Mul,
    "Pow": sp.Pow,
    "sqrt": sp.sqrt,
    "log": sp.log,
    "ln": sp.log,
    "lg": _lg,
    "exp": sp.exp,
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "tg": sp.tan,
    "cot": sp.cot,
    "ctg": sp.cot,
    "Abs": sp.Abs,
    "abs": sp.Abs,
    "pi": sp.pi,
}
_PLAIN_TRANSFORMATIONS = (
    auto_symbol,
    auto_number,
    convert_xor,
    implicit_multiplication_application,
)


def _matching(text: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _braced_groups(text: str, marker: re.Pattern[str]) -> str:
    result = []
    position = 0
    for match in marker.finditer(text):
        if match.start() < position:
            continue
        open_index = match.end() - 1
        close_index = _matching(text, open_index, "(", ")")
        if close_index < 0:
            continue
        result.append(text[position:open_index])
        result.append("{" + text[open_index + 1 : close_index] + "}")
        position = close_index + 1
    result.append(text[position:])
    return "".join(result)


def _normalize(text: str) -> str:
    text = text.replace("\\\\", " ¶ ")
    for old, new in _CHAR_REPLACEMENTS:
        text = text.replace(old, new)
    text = re.sub(
        r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+", lambda m: "^{" + m.group().translate(_SUPERSCRIPT) + "}", text
    )
    text = re.sub(r"[₀₁₂₃₄₅₆₇₈₉]+", lambda m: "_{" + m.group().translate(_SUBSCRIPT) + "}", text)
    for pattern, replacement in _LATEX_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"_\{?\s*(\d)\s*[,;.]\s*(\d)\s*\}?", r"_{\1\2}", text)
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    return re.sub(r"\s+", " ", text).strip()


def _latexify(text: str) -> str:
    text = text.replace("**", "^")
    text = _PLAIN_FUNCTIONS.sub(lambda m: _FUNCTION_LATEX[m.group(1)], text)
    text = re.sub(r"\\log\s*(\d+)\s*(?=[({a-zA-Z\\])", r"\\log_{\1}", text)
    text = _braced_groups(text, re.compile(r"\\sqrt\s*\("))
    text = _braced_groups(text, re.compile(r"\^\s*\("))
    text = _braced_groups(text, re.compile(r"_\s*\("))
    text = re.sub(r"\\sqrt\s*(\d+(?:\.\d+)?|[a-zA-Z])", r"\\sqrt{\1}", text)
    text = re.sub(r"\^\s*(-?\d+(?:\.\d+)?)", r"^{\1}", text)
    text = re.sub(r"(?<!\\)\*", r" \\cdot ", text)
    return text.replace(":", "/")


def _count_nodes(expr: Any) -> int:
    count = 0
    for _ in sp.preorder_traversal(expr):
        count += 1
        if count > MAX_NODES:
            break
    return count


def _check_power(base: Any, exponent: Any) -> None:
    if exponent.is_Integer:
        size = abs(int(exponent))
        if base.is_Rational:
            bits = max(int(base.p).bit_length(), int(base.q).bit_length(), 1)
            if size * bits > MAX_EXPONENT_BITS:
                raise ParseRejected("too_large")
        elif base.is_Number:
            if size > MAX_DEGREE * 8:
                raise ParseRejected("too_large")
        elif size > MAX_DEGREE * 4:
            raise ParseRejected("too_large")
    elif exponent.is_Number and abs(exponent) > MAX_EXPONENT_BITS:
        raise ParseRejected("too_large")


def _evaluate(node: Any) -> Any:
    if isinstance(node, sp.UnevaluatedExpr):
        return _evaluate(node.args[0])
    if node.is_Float:
        return sp.Rational(str(node))
    if node.is_Symbol:
        name = str(node.name)
        if not _SYMBOL_NAME.match(name):
            raise ParseRejected("bad_symbol")
        return sp.Symbol(name.replace("{", "").replace("}", "").replace(",", ""), real=True)
    if node.is_Integer:
        if len(str(abs(int(node)))) > MAX_INTEGER_DIGITS:
            raise ParseRejected("too_large")
        return node
    if node.is_Atom:
        if node.is_Number or node in (sp.pi, sp.E, sp.oo, -sp.oo, sp.zoo):
            return node
        raise ParseRejected("unsupported")
    if not (node.is_Add or node.is_Mul or node.is_Pow or isinstance(node, _ALLOWED_FUNCTIONS)):
        raise ParseRejected("unsupported")
    args = [_evaluate(arg) for arg in node.args]
    if node.is_Pow:
        _check_power(args[0], args[1])
    result = node.func(*args)
    if result.is_Rational and max(abs(int(result.p)), int(result.q)).bit_length() > 200:
        raise ParseRejected("too_large")
    return result


def _strip_raw(node: Any) -> Any:
    if isinstance(node, sp.UnevaluatedExpr):
        return _strip_raw(node.args[0])
    if node.is_Float:
        return sp.Rational(str(node))
    if node.is_Symbol:
        name = str(node.name).replace("{", "").replace("}", "").replace(",", "")
        return sp.Symbol(name, real=True)
    if node.is_Atom:
        return node
    return node.func(*[_strip_raw(arg) for arg in node.args], evaluate=False)


def _parse_plain(text: str) -> Any:
    if not _PLAIN_ALLOWED.match(text):
        raise ParseRejected("syntax")
    if re.search(r"\.(?!\d)|(?<!\d)\.", text):
        raise ParseRejected("forbidden")
    for identifier in _IDENTIFIER.findall(text):
        if identifier.lower() in _KEYWORDS or identifier.startswith("_"):
            raise ParseRejected("forbidden")
    try:
        return parse_expr(
            text,
            local_dict={},
            global_dict=dict(_PLAIN_GLOBALS),
            transformations=_PLAIN_TRANSFORMATIONS,
            evaluate=False,
        )
    except MathTimeout:
        raise
    except Exception as exc:
        raise ParseRejected("syntax") from exc


def _parse_raw(text: str) -> Any:
    text = text.strip()
    if not text:
        raise ParseRejected("empty")
    if "__" in text or "'" in text or '"' in text:
        raise ParseRejected("forbidden")
    if any(word.lower() in _DANGEROUS for word in _IDENTIFIER.findall(text)):
        raise ParseRejected("forbidden")
    try:
        raw = latex2sympy(_latexify(text))
    except MathTimeout:
        raise
    except Exception:
        raw = _parse_plain(text)
    if not isinstance(raw, sp.Expr):
        raise ParseRejected("not_expression")
    if _count_nodes(raw) > MAX_NODES:
        raise ParseRejected("too_complex")
    return raw


def _parse_pair(text: str) -> tuple[Any, Any]:
    raw = _parse_raw(text)
    value = _evaluate(raw)
    if value.has(sp.zoo, sp.nan):
        raise ParseRejected("undefined")
    return value, _strip_raw(raw)


def _scan(text: str) -> list[tuple[int, str]]:
    tokens: list[tuple[int, str]] = []
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(depth - 1, 0)
        elif depth == 0:
            pair = text[index : index + 2]
            if pair in ("<=", ">=", "!="):
                tokens.append((index, pair))
                index += 2
                continue
            if char in "=<>,;∨":
                tokens.append((index, char))
        index += 1
    return tokens


def _split(text: str, separators: str) -> list[str]:
    pieces = []
    start = 0
    for position, token in _scan(text):
        if token in separators and len(token) == 1:
            pieces.append(text[start:position])
            start = position + 1
    pieces.append(text[start:])
    return [piece.strip() for piece in pieces if piece.strip()]


def _split_relation(text: str) -> tuple[list[str], list[Op]]:
    parts = []
    ops = []
    start = 0
    for position, token in _scan(text):
        if token in (",", ";", "∨"):
            continue
        parts.append(text[start:position])
        ops.append(Op(token))
        start = position + len(token)
    parts.append(text[start:])
    return [part.strip() for part in parts], ops


def _expand_plus_minus(piece: str) -> list[str]:
    if "±" not in piece:
        return [piece]
    parts, ops = _split_relation(piece)
    last = max(index for index, part in enumerate(parts) if "±" in part)
    kept = parts[: last + 1]
    rebuilt = []
    for sign in ("+", "-"):
        chunks = [kept[0]]
        for op, part in zip(ops[:last], kept[1:], strict=True):
            chunks.append(op.value)
            chunks.append(part.replace("±", sign))
        rebuilt.append(" ".join(chunks).replace("±", sign))
    return rebuilt


@dataclass(frozen=True, slots=True)
class _Relation:
    parts: tuple[Any, ...]
    raw: tuple[Any, ...]
    ops: tuple[Op, ...]
    continuation: bool


def _parse_relation(piece: str) -> _Relation:
    texts, ops = _split_relation(piece)
    continuation = False
    if texts and not texts[0] and ops and ops[0] is Op.EQ:
        texts = texts[1:]
        ops = ops[1:]
        continuation = True
    if any(not text for text in texts):
        raise ParseRejected("syntax")
    values: list[Any] = []
    raws: list[Any] = []
    kept_ops: list[Op] = []
    for index, text in enumerate(texts):
        if "'" in text and 0 < index < len(texts) - 1:
            continue
        value, raw = _parse_pair(text)
        if values:
            kept_ops.append(ops[index - 1])
        values.append(value)
        raws.append(raw)
    return _Relation(tuple(values), tuple(raws), tuple(kept_ops), continuation)


def _is_assignment(relation: _Relation) -> bool:
    return (
        len(relation.parts) == 2
        and relation.ops == (Op.EQ,)
        and relation.parts[0].is_Symbol
        and not relation.parts[1].free_symbols
    )


def base_name(symbol: Any) -> str:
    return str(symbol.name).split("_")[0]


def base_symbol(symbol: Any) -> Any:
    return sp.Symbol(base_name(symbol), real=True)


def _to_member(relation: _Relation) -> Equation | Inequality:
    if relation.ops == (Op.EQ,):
        return Equation(relation.parts[0], relation.parts[1], relation.raw[0], relation.raw[1])
    if relation.ops and all(op in INEQUALITY_OPS or op is Op.NE for op in relation.ops):
        return Inequality(relation.parts, relation.ops, relation.raw)
    raise ParseRejected("mixed_relations")


def _single(relation: _Relation) -> Statement:
    if not relation.ops:
        return Expression(relation.parts[0], relation.raw[0], relation.continuation)
    if relation.continuation or len(relation.parts) > 2:
        if all(op in INEQUALITY_OPS for op in relation.ops) and not relation.continuation:
            return Inequality(relation.parts, relation.ops, relation.raw)
        return Chain(relation.parts, relation.ops, relation.raw, relation.continuation)
    if relation.ops == (Op.EQ,):
        return Equation(relation.parts[0], relation.parts[1], relation.raw[0], relation.raw[1])
    if relation.ops[0] in INEQUALITY_OPS or relation.ops[0] is Op.NE:
        return Inequality(relation.parts, relation.ops, relation.raw)
    return Chain(relation.parts, relation.ops, relation.raw)


def _answer_from_assignments(relations: list[_Relation], *, explicit: bool) -> Answer | None:
    if not relations or not all(_is_assignment(relation) for relation in relations):
        return None
    names = [base_name(relation.parts[0]) for relation in relations]
    values = [relation.parts[1] for relation in relations]
    if len(set(names)) == 1:
        return Answer(base_symbol(relations[0].parts[0]), sp.FiniteSet(*values), explicit=explicit)
    if len(set(names)) == len(names):
        variables = tuple(sp.Symbol(name, real=True) for name in names)
        return Answer(None, sp.EmptySet, (tuple(values),), variables, explicit=explicit)
    return None


def _endpoint(text: str) -> Any:
    cleaned = text.strip().replace(" ", "")
    if cleaned in (r"\infty", r"+\infty", "+oo", "oo"):
        return sp.oo
    if cleaned in (r"-\infty", "-oo"):
        return -sp.oo
    value, _ = _parse_pair(text)
    if value.free_symbols:
        raise ParseRejected("syntax")
    return value


def _parse_set(text: str) -> tuple[Any, tuple[tuple[Any, ...], ...]] | None:
    pieces = [piece.strip() for piece in re.split(r"∪|(?<=[)\]])\s*U\s*(?=[(\[])", text)]
    result: Any = sp.EmptySet
    points: list[tuple[Any, ...]] = []
    for piece in pieces:
        interval = re.fullmatch(r"([(\[])(.*)([)\]])", piece)
        braces = re.fullmatch(r"\\?\{(.*?)\\?\}", piece)
        if braces is not None:
            elements = _split(braces.group(1), ";,")
            result = result.union(sp.FiniteSet(*[_endpoint(item) for item in elements]))
        elif interval is not None:
            inner = interval.group(2)
            ends = _split(inner, ";")
            if len(ends) != 2:
                ends = _split(inner, ",")
            if len(ends) != 2:
                return None
            low, high = _endpoint(ends[0]), _endpoint(ends[1])
            left_open = interval.group(1) == "(" or low == -sp.oo
            right_open = interval.group(3) == ")" or high == sp.oo
            result = result.union(sp.Interval(low, high, left_open, right_open))
            if low.is_finite and high.is_finite and interval.group(1) == "(" and right_open:
                points.append((low, high))
        else:
            return None
    return result, tuple(points)


def _looks_like_set(text: str) -> bool:
    stripped = text.strip()
    if "∪" in stripped or r"\infty" in stripped:
        return stripped[:1] in "([" or stripped.startswith("\\{")
    return bool(re.fullmatch(r"(?:\(|\[|\\?\{).*[;].*(?:\)|\]|\\?\})", stripped))


def _parse_system(body: str) -> Statement:
    rows = [row.replace("&", " ").strip() for row in body.split("¶")]
    members: list[Equation | Inequality] = []
    for row in rows:
        for piece in _split(row, ",;"):
            members.append(_to_member(_parse_relation(piece)))
    if not members:
        raise ParseRejected("empty")
    return System(tuple(members))


def _symbols_of(relations: list[_Relation]) -> set[Any]:
    found: set[Any] = set()
    for relation in relations:
        for part in relation.parts:
            found |= part.free_symbols
    return found


def _interpret(text: str, *, explicit: bool) -> Statement:
    cases = _CASES.search(text)
    if cases is not None:
        return _parse_system(cases.group(2))
    brace = re.fullmatch(r"\\?\{(.*?)(?:\\?\})?", text)
    if brace is not None and any(token in brace.group(1) for token in "=<>"):
        return _parse_system(brace.group(1).replace(";", "¶").replace(",", "¶"))
    membership = re.match(r"^(.*?)\\in(?![a-zA-Z])(.*)$", text)
    if membership is not None:
        variable = None
        if membership.group(1).strip():
            variable, _ = _parse_pair(membership.group(1))
            if not variable.is_Symbol:
                raise ParseRejected("syntax")
            variable = base_symbol(variable)
        target = membership.group(2).strip()
        if target in ("ℝ", r"(-\infty;+\infty)"):
            return Answer(variable, sp.Reals, explicit=True)
        if "∅" in target:
            return Answer(variable, sp.EmptySet, explicit=True)
        parsed = _parse_set(target)
        if parsed is None:
            raise ParseRejected("syntax")
        return Answer(variable, parsed[0], explicit=True)
    if _looks_like_set(text):
        parsed = _parse_set(text)
        if parsed is not None:
            return Answer(None, parsed[0], parsed[1], explicit=True)
    label = _DERIVATIVE_LABEL.match(text)
    if label is not None and (label.group("prime") or "(" in label.group(0)):
        name = label.group(1) + ("'" if label.group("prime") else "")
        relation = _parse_relation(text[label.end() :])
        if not relation.ops:
            return Expression(relation.parts[0], relation.raw[0], label=name)
        return Chain(relation.parts, relation.ops, relation.raw, continuation=True)
    alternative = "∨" in text
    pieces = [expanded for piece in _split(text, ",;∨") for expanded in _expand_plus_minus(piece)]
    if not pieces:
        raise ParseRejected("empty")
    relations = [_parse_relation(piece) for piece in pieces]
    if len(relations) == 1 and not explicit and len(pieces) == 1:
        return _single(relations[0])
    answer = _answer_from_assignments(relations, explicit=explicit)
    if answer is not None:
        return answer
    if all(not relation.ops for relation in relations):
        values = [relation.parts[0] for relation in relations]
        if explicit or all(not value.free_symbols for value in values):
            return Answer(None, sp.FiniteSet(*values), explicit=explicit)
        if len(relations) == 1:
            return _single(relations[0])
        raise ParseRejected("syntax")
    if len(relations) == 1:
        relation = relations[0]
        statement = _single(relation)
        if explicit and isinstance(statement, Inequality):
            variables = _symbols_of(relations)
            if len(variables) == 1 and any(part.is_Symbol for part in relation.parts):
                return statement
        return statement
    relations = [relation for relation in relations if relation.ops]
    members = tuple(_to_member(relation) for relation in relations)
    if alternative:
        return Disjunction(members)
    symbols = _symbols_of(relations)
    if len(symbols) >= 2:
        return System(members)
    if all(isinstance(member, Equation) for member in members):
        return Disjunction(members)
    return System(members)


def _prepare(text: str) -> tuple[str, dict[str, bool]]:
    flags = {"answer": False, "domain": False, "reject": False, "empty": False, "all": False}
    text = _normalize(text)
    text = _NUMBERING.sub("", text)
    if _ANSWER_PREFIX.match(text):
        flags["answer"] = True
        text = _ANSWER_PREFIX.sub("", text, count=1)
    if _DOMAIN_PREFIX.match(text):
        flags["domain"] = True
        text = _DOMAIN_PREFIX.sub("", text, count=1)
    if _REJECT.search(text):
        flags["reject"] = True
    if _EMPTY.search(text) or "∅" in text:
        flags["empty"] = True
    elif _ALL.search(text) or "ℝ" in text:
        flags["all"] = True
    text = _OR.sub(" ∨ ", text)
    text = _AND.sub(" ; ", text)
    flags["words"] = bool(_CYRILLIC.search(text))
    text = _CYRILLIC.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;.∨").rstrip(" -")
    return text, flags


def _parse(text: str) -> Statement:
    if len(text) > MAX_INPUT_LENGTH:
        return Unparseable("too_long")
    prepared, flags = _prepare(text)
    explicit = flags["answer"]
    if flags["empty"] or flags["all"]:
        values = sp.EmptySet if flags["empty"] else sp.Reals
        variable = None
        symbol = re.match(r"^\s*([a-zA-Z])(?:_\{?\d+\}?)?\b", prepared)
        if symbol is not None:
            variable = sp.Symbol(symbol.group(1), real=True)
        return Answer(variable, values, explicit=True)
    if not re.search(r"[0-9a-zA-Z]", prepared):
        return Note(NoteKind.TEXT)
    if flags["domain"] or flags["reject"]:
        kind = NoteKind.DOMAIN if flags["domain"] else NoteKind.REJECT
        try:
            inner = _interpret(prepared, explicit=False)
        except ParseRejected:
            inner = None
        return Note(kind, inner)
    try:
        statement = _interpret(prepared, explicit=explicit)
    except ParseRejected as exc:
        if flags["words"]:
            return Note(NoteKind.TEXT)
        return Unparseable(exc.reason)
    if isinstance(statement, Equation | Inequality) and explicit:
        return _explicit_answer(statement)
    if isinstance(statement, Inequality) and Op.NE in statement.ops and len(statement.ops) == 1:
        return Note(NoteKind.DOMAIN, statement)
    return statement


def _explicit_answer(statement: Equation | Inequality) -> Statement:
    if isinstance(statement, Equation):
        if statement.lhs.is_Symbol and not statement.rhs.free_symbols:
            return Answer(base_symbol(statement.lhs), sp.FiniteSet(statement.rhs), explicit=True)
        return statement
    symbols: set[Any] = set()
    for part in statement.parts:
        symbols |= part.free_symbols
    if len(symbols) != 1 or not any(part.is_Symbol for part in statement.parts):
        return statement
    variable = next(iter(symbols))
    solution: Any = sp.Reals
    for left, op, right in zip(statement.parts, statement.ops, statement.parts[1:], strict=False):
        solution = solution.intersect(sp.solveset(relational(left, op, right), variable, sp.Reals))
    return Answer(base_symbol(variable), solution, explicit=True)


@lru_cache(maxsize=1024)
def parse_line(text: str) -> Statement:
    try:
        with time_limit(2.0):
            return _parse(text)
    except MathTimeout:
        reraise_if_expired()
        return Unparseable("timeout")
    except ParseRejected as exc:
        return Unparseable(exc.reason)
    except (RecursionError, MemoryError):
        return Unparseable("too_complex")
    except Exception:
        return Unparseable("syntax")


def parse_steps(text: str) -> list[Statement]:
    if len(text) > MAX_INPUT_LENGTH:
        return [Unparseable("too_long")]
    chunks = [chunk for chunk in _normalize(text).split("⇒") if chunk.strip()]
    if len(chunks) <= 1:
        return [parse_line(text)]
    return [parse_line(chunk) for chunk in chunks]


@lru_cache(maxsize=1024)
def parse_expression(text: str) -> Any | None:
    if len(text) > MAX_INPUT_LENGTH:
        return None
    try:
        with time_limit(2.0):
            value, _ = _parse_pair(_normalize(text))
    except MathTimeout:
        reraise_if_expired()
        return None
    except ParseRejected:
        return None
    except Exception:
        return None
    return value
