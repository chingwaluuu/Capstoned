"""Safe, focused MathML rendering for math expressions embedded in prose."""

from __future__ import annotations

import re
from html import escape

from markupsafe import Markup


NUMBER = r"\d+(?:\.\d+)?"
ELLIPSIS_DECIMAL = rf"{NUMBER}(?:\.\.\.|…)"
MIXED_NUMBER = r"\d+\s+\d+/\d+"
FRACTION = r"\d+/\d+"
PAREN_GROUP = r"\([^()]*\)"
VARIABLE = r"(?:\d+)?[A-Za-z]"
ATOM = rf"(?:{MIXED_NUMBER}|{PAREN_GROUP}|{FRACTION}|{ELLIPSIS_DECIMAL}|{VARIABLE}|{NUMBER})"
OPERATOR = r"(?:=|\+|−|×|÷|\*|-|/)"
RUN_RE = re.compile(rf"(?<![\w])(?P<run>{ATOM}(?:\s*{OPERATOR}\s*{ATOM})*)(?![\w])")
TOKEN_RE = re.compile(rf"\s*(?P<operator>{OPERATOR})|\s*(?P<atom>{ATOM})")
FRACTION_RE = re.compile(r"^(\d+)/(\d+)$")
MIXED_RE = re.compile(r"^(\d+)\s+(\d+)/(\d+)$")
COEFFICIENT_RE = re.compile(r"^(\d+)([A-Za-z])$")
ELLIPSIS_RE = re.compile(r"^(\d+(?:\.\d+)?)(?:\.\.\.|…)$")


def _number(value: str) -> str:
    return f"<mn>{value}</mn>"


def _fraction(numerator: str, denominator: str) -> str:
    return f"<mfrac><mn>{numerator}</mn><mn>{denominator}</mn></mfrac>"


def _atom_mathml(atom: str) -> str:
    atom = atom.strip()
    mixed = MIXED_RE.fullmatch(atom)
    if mixed:
        whole, numerator, denominator = mixed.groups()
        return _number(whole) + _fraction(numerator, denominator)

    fraction = FRACTION_RE.fullmatch(atom)
    if fraction:
        return _fraction(*fraction.groups())

    ellipsis = ELLIPSIS_RE.fullmatch(atom)
    if ellipsis:
        return _repeating_decimal_mathml(ellipsis.group(1))

    coefficient = COEFFICIENT_RE.fullmatch(atom)
    if coefficient:
        return _number(coefficient.group(1)) + f"<mi>{coefficient.group(2)}</mi>"

    if atom.startswith("(") and atom.endswith(")"):
        inner = atom[1:-1]
        return "<mo>(</mo>" + _expression_mathml(inner) + "<mo>)</mo>"

    if re.fullmatch(r"[A-Za-z]", atom):
        return f"<mi>{atom}</mi>"

    return _number(atom)


def _repeating_decimal_mathml(decimal: str) -> str:
    """Use an overline for a clearly repeated decimal suffix instead of trailing dots."""
    integer, digits = decimal.split(".", 1)
    for period in range(1, len(digits) // 2 + 1):
        for suffix_length in range(len(digits), period * 2 - 1, -1):
            if suffix_length % period:
                continue
            suffix_start = len(digits) - suffix_length
            repeated = digits[suffix_start:]
            block = repeated[:period]
            if all(repeated[index] == block[index % period] for index in range(len(repeated))):
                nonrepeating = digits[:suffix_start]
                head = _number(f"{integer}.{nonrepeating}")
                bar = f'<mover accent="true"><mn>{block}</mn><mo>¯</mo></mover>'
                return head + bar
    return _number(decimal) + "<mo>…</mo>"


def _expression_mathml(expression: str) -> str:
    """Convert already-escaped expression text into MathML nodes."""
    tokens: list[tuple[str, str]] = []
    position = 0
    while position < len(expression):
        match = TOKEN_RE.match(expression, position)
        if not match:
            position += 1
            continue
        if match.group("operator") is not None:
            tokens.append(("operator", match.group("operator")))
        else:
            tokens.append(("atom", match.group("atom")))
        position = match.end()

    rendered: list[str] = []
    index = 0
    while index < len(tokens):
        kind, token = tokens[index]
        if kind == "operator" and token == "/" and rendered and index + 1 < len(tokens):
            numerator = rendered.pop()
            denominator_kind, denominator_token = tokens[index + 1]
            if denominator_kind == "atom":
                denominator = _atom_mathml(denominator_token)
                rendered.append(f"<mfrac><mrow>{numerator}</mrow><mrow>{denominator}</mrow></mfrac>")
                index += 2
                continue
            rendered.append(numerator)
        elif kind == "atom":
            rendered.append(_atom_mathml(token))
        else:
            operator = "×" if token == "*" else "−" if token == "-" else token
            rendered.append(f"<mo>{operator}</mo>")
        index += 1

    return "".join(rendered)


def _is_math_run(run: str) -> bool:
    if "/" in run or re.search(r"(?:\.\.\.|…)", run):
        return True
    if re.search(r"[=+−×÷*-]", run):
        return True
    return bool(re.fullmatch(r"\([^()]*[=+−×÷*/-][^()]*\)", run))


def _is_page_range(text: str, start: int) -> bool:
    return bool(re.search(r"\bpp?\.\s*$", text[max(0, start - 8):start], re.IGNORECASE))


def render_math(text: object) -> Markup:
    """Escape source text, then convert only recognizable math runs into MathML."""
    escaped = escape(str(text or ""), quote=False)
    source = str(escaped)
    output: list[str] = []
    cursor = 0

    for match in RUN_RE.finditer(source):
        run = match.group("run")
        if not _is_math_run(run) or _is_page_range(source, match.start()):
            continue
        output.append(source[cursor:match.start()])
        body = _expression_mathml(run)
        output.append(f'<math display="inline"><mrow>{body}</mrow></math>')
        cursor = match.end()

    output.append(source[cursor:])
    return Markup("".join(output))
