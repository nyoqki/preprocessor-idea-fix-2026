from datetime import UTC, datetime

from yasno.db.models import TopicProgress
from yasno.services.progress import MAX_BOX, REVIEW_INTERVALS, GapStatus, schedule, status_for

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)


def test_mistake_resets_box_and_schedules_first_review() -> None:
    assert schedule(3, correct=False, now=NOW) == (0, NOW + REVIEW_INTERVALS[0])


def test_success_promotes_box_until_mastered() -> None:
    box = 0
    reviews = []
    for _ in range(MAX_BOX):
        box, due = schedule(box, correct=True, now=NOW)
        reviews.append(due)
    assert box == MAX_BOX
    assert reviews[-1] is None
    assert reviews[0] == NOW + REVIEW_INTERVALS[1]


def test_status_reflects_box() -> None:
    assert status_for(TopicProgress(mistakes_total=2, box=0)) is GapStatus.WEAK
    assert status_for(TopicProgress(mistakes_total=2, box=2)) is GapStatus.IMPROVING
    assert status_for(TopicProgress(mistakes_total=2, box=MAX_BOX)) is GapStatus.SOLID
    assert status_for(TopicProgress(mistakes_total=0, box=0)) is GapStatus.SOLID
