from collections.abc import Sequence

from yasno.ai.latex import latex_to_plain, plain, similarity
from yasno.ai.types import OcrResult, TranscribedLine


def _line_key(line: TranscribedLine) -> str:
    return latex_to_plain(line.latex) if line.latex else plain(line.text)


def align(left: Sequence[str], right: Sequence[str], threshold: float) -> list[tuple[int, int]]:
    rows, cols = len(left), len(right)
    scores = [[similarity(a, b) for b in right] for a in left]
    best = [[0.0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            score = scores[i - 1][j - 1]
            diagonal = best[i - 1][j - 1] + score if score >= threshold else -1.0
            best[i][j] = max(best[i - 1][j], best[i][j - 1], diagonal)
    pairs: list[tuple[int, int]] = []
    i, j = rows, cols
    while i > 0 and j > 0:
        score = scores[i - 1][j - 1]
        if score >= threshold and best[i][j] == best[i - 1][j - 1] + score:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif best[i][j] == best[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def attach_bboxes(
    lines: Sequence[TranscribedLine], ocr: OcrResult, *, threshold: float = 0.5
) -> list[TranscribedLine]:
    result = list(lines)
    if not result or not ocr.lines:
        return result
    pairs = align(
        [_line_key(line) for line in result],
        [plain(line.text) for line in ocr.lines],
        threshold,
    )
    for line_index, ocr_index in pairs:
        bbox = ocr.lines[ocr_index].bbox
        if bbox is not None and result[line_index].bbox is None:
            result[line_index] = result[line_index].model_copy(update={"bbox": bbox})
    return result
