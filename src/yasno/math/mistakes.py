from collections.abc import Iterator
from typing import Any

import sympy as sp

from yasno.math.equivalence import evaluate_tree
from yasno.math.errors import ErrorType

MAX_MUTATIONS = 60
MAX_NODES_VISITED = 80

type Mutation = tuple[Any, ErrorType]


def _terms(tree: Any) -> list[Any]:
    return list(tree.args) if tree.is_Add else [tree]


def _negate(term: Any) -> Any:
    return sp.Mul(-1, term, evaluate=False)


def _split_coefficient(term: Any) -> tuple[Any, Any]:
    coefficient, rest = evaluate_tree(term).as_coeff_Mul()
    return coefficient, rest


def _square_mistakes(base: Any) -> Iterator[Mutation]:
    terms = _terms(base)
    if len(terms) != 2:
        return
    first, second = (evaluate_tree(term) for term in terms)
    yield first**2 + second**2, ErrorType.DISTRIBUTION
    coefficient, rest = _split_coefficient(second)
    if coefficient < 0:
        yield first**2 - (coefficient * rest) ** 2, ErrorType.DISTRIBUTION
    yield first**2 + first * second + second**2, ErrorType.DISTRIBUTION
    yield first**2 - 2 * first * second + second**2, ErrorType.SIGN


def _power_mistakes(node: Any) -> Iterator[Mutation]:
    base, exponent = node.args
    if base.is_Add and exponent == 2:
        yield from _square_mistakes(base)
    elif base.is_Add and exponent.is_Integer and exponent > 2:
        yield (
            sp.Add(*[evaluate_tree(term) ** exponent for term in base.args]),
            (ErrorType.DISTRIBUTION),
        )
    if base.is_Pow:
        inner_base, inner_exponent = base.args
        yield (
            evaluate_tree(inner_base) ** (evaluate_tree(inner_exponent) + exponent),
            (ErrorType.POWERS),
        )
    if base.is_Mul and exponent.is_Integer:
        factors = [evaluate_tree(factor) for factor in base.args]
        yield sp.Mul(*factors[:-1]) * factors[-1] ** exponent, ErrorType.POWERS
    if exponent.is_Integer and exponent < 0 and not base.is_Number:
        yield -(evaluate_tree(base) ** -exponent), ErrorType.POWERS
    if exponent == sp.Rational(1, 2):
        if base.is_Add:
            yield sp.Add(*[sp.sqrt(evaluate_tree(term)) for term in base.args]), ErrorType.ROOTS
        if base.is_Integer and base > 0:
            yield base / 2, ErrorType.ROOTS
        if base.is_Pow and base.exp == 2:
            yield evaluate_tree(base.base), ErrorType.ROOTS
    if exponent == 0:
        yield sp.Integer(0), ErrorType.POWERS


def _product_mistakes(node: Any) -> Iterator[Mutation]:
    factors = list(node.args)
    sums = [factor for factor in factors if factor.is_Add]
    others = [evaluate_tree(factor) for factor in factors if not factor.is_Add]
    multiplier = sp.Mul(*others)
    if len(sums) == 1:
        terms = [evaluate_tree(term) for term in sums[0].args]
        yield multiplier * terms[0] + sp.Add(*terms[1:]), ErrorType.DISTRIBUTION
        coefficient, rest = multiplier.as_coeff_Mul()
        if coefficient != 1 and rest != 1:
            yield rest * (coefficient * terms[0] + sp.Add(*terms[1:])), ErrorType.DISTRIBUTION
        if coefficient < 0:
            flipped = terms[0] - sp.Add(*terms[1:])
            yield multiplier * flipped, ErrorType.SIGN
    if len(sums) == 2:
        first = [evaluate_tree(term) for term in sums[0].args]
        second = [evaluate_tree(term) for term in sums[1].args]
        if len(first) == 2 and len(second) == 2:
            yield (
                multiplier * (first[0] * second[0] + first[1] * second[1]),
                (ErrorType.DISTRIBUTION),
            )
    powers: dict[Any, list[Any]] = {}
    for factor in factors:
        if factor.is_Pow and not factor.base.is_Add:
            powers.setdefault(evaluate_tree(factor.base), []).append(evaluate_tree(factor.exp))
    for base, exponents in powers.items():
        if len(exponents) == 2:
            rest = [
                evaluate_tree(factor)
                for factor in factors
                if not (factor.is_Pow and evaluate_tree(factor.base) == base)
            ]
            product = exponents[0] * exponents[1]
            if exponents[1].is_negative:
                yield sp.Mul(*rest) * base ** (exponents[0] / -exponents[1]), ErrorType.POWERS
            yield sp.Mul(*rest) * base**product, ErrorType.POWERS


def _sum_mistakes(node: Any) -> Iterator[Mutation]:
    terms = [evaluate_tree(term) for term in node.args]
    if len(terms) <= 6:
        for index in range(len(terms)):
            flipped = [-term if position == index else term for position, term in enumerate(terms)]
            yield sp.Add(*flipped), ErrorType.SIGN
    fractions = [sp.fraction(term) for term in terms]
    with_denominators = [
        (numerator, denominator) for numerator, denominator in fractions if denominator != 1
    ]
    if len(terms) == 2 and len(with_denominators) == 2:
        (a, b), (c, d) = fractions
        yield (a + c) / (b + d), ErrorType.FRACTIONS
        if b != d:
            yield (a + c) / (b * d), ErrorType.FRACTIONS
    for position, term in enumerate(node.args):
        coefficient, rest = _split_coefficient(term)
        numerator, denominator = sp.fraction(rest)
        if coefficient < 0 and numerator.is_Add and denominator != 1:
            parts = list(numerator.args)
            wrong = (coefficient * parts[0] + sp.Add(*parts[1:])) / denominator
            others = [
                evaluate_tree(arg) for index, arg in enumerate(node.args) if index != position
            ]
            yield sp.Add(*others) + wrong, ErrorType.SIGN


def _node_mutations(node: Any) -> Iterator[Mutation]:
    if node.is_Pow:
        yield from _power_mistakes(node)
    elif node.is_Mul:
        yield from _product_mistakes(node)
    elif node.is_Add:
        yield from _sum_mistakes(node)


def expression_mutations(tree: Any) -> list[Mutation]:
    found: list[Mutation] = []
    visited = 0
    for node in sp.preorder_traversal(tree):
        visited += 1
        if visited > MAX_NODES_VISITED or len(found) >= MAX_MUTATIONS:
            break
        if node.is_Atom:
            continue
        for replacement, error in _node_mutations(node):
            mutated = (
                evaluate_tree(tree.xreplace({node: replacement})) if node != tree else (replacement)
            )
            found.append((mutated, error))
            if len(found) >= MAX_MUTATIONS:
                break
    return found


def transfer_mutations(lhs: Any, rhs: Any) -> list[Any]:
    difference = evaluate_tree(lhs) - evaluate_tree(rhs)
    candidates = []
    for term in _terms(lhs):
        if len(_terms(lhs)) > 1 or rhs != 0:
            candidates.append(difference - 2 * evaluate_tree(term))
    for term in _terms(rhs):
        if len(_terms(rhs)) > 1 or lhs != 0:
            candidates.append(difference + 2 * evaluate_tree(term))
    return candidates


def equation_mutations(lhs: Any, rhs: Any) -> list[Mutation]:
    found: list[Mutation] = [
        (candidate, ErrorType.SIGN) for candidate in transfer_mutations(lhs, rhs)
    ]
    right = evaluate_tree(rhs)
    left = evaluate_tree(lhs)
    found.extend((mutated - right, error) for mutated, error in expression_mutations(lhs))
    found.extend((left - mutated, error) for mutated, error in expression_mutations(rhs))
    return found
