from datetime import datetime

from pydantic import BaseModel, Field

from yasno.db.models import ConsentStatus, QuizReason, QuizStatus, Role, SubmissionStatus
from yasno.services.progress import GapStatus


class ClassOut(BaseModel):
    id: int
    title: str
    grade: int | None


class MeOut(BaseModel):
    id: int
    first_name: str
    last_name: str | None
    role: Role
    grade: int | None
    consent_status: ConsentStatus
    school_class: ClassOut | None


class ErrorTypeCount(BaseModel):
    code: str
    title: str
    count: int


class TopicGapOut(BaseModel):
    code: str
    title: str
    status: GapStatus
    mistakes_total: int
    correct_total: int
    last_mistake_at: datetime | None
    next_review_at: datetime | None
    error_types: list[ErrorTypeCount]


class GapSummary(BaseModel):
    weak: int = 0
    improving: int = 0
    solid: int = 0


class GapMapOut(BaseModel):
    topics: list[TopicGapOut]
    summary: GapSummary


class BBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class SubmissionOut(BaseModel):
    id: int
    created_at: datetime
    status: SubmissionStatus
    verdict: str | None
    topic_code: str | None
    topic_title: str | None
    error_type: str | None
    error_title: str | None
    first_error_step: int | None
    image_url: str | None


class SubmissionPage(BaseModel):
    items: list[SubmissionOut]
    next_cursor: str | None


class LineOut(BaseModel):
    index: int
    latex: str
    display: str
    confidence: float
    bbox: BBox | None
    is_error: bool


class AnalysisOut(BaseModel):
    status: str | None
    first_error_step: int | None
    error_type: str | None
    error_title: str | None
    hint: str | None


class SubmissionDetail(SubmissionOut):
    task: str | None
    lines: list[LineOut]
    analysis: AnalysisOut | None
    error_bbox: BBox | None
    finished_at: datetime | None


class QuizSummary(BaseModel):
    id: int
    reason: QuizReason
    status: QuizStatus
    created_at: datetime
    total: int
    answered: int
    correct: int
    topic_titles: list[str]


class ActiveQuizOut(BaseModel):
    quiz: QuizSummary | None


class ChoiceOut(BaseModel):
    index: int
    text: str


class QuizItemOut(BaseModel):
    id: int
    position: int
    topic_code: str
    topic_title: str
    prompt: str
    choices: list[ChoiceOut]
    from_gap_map: bool
    answered_index: int | None
    correct_index: int | None
    is_correct: bool | None


class QuizOut(QuizSummary):
    items: list[QuizItemOut]


class AnswerIn(BaseModel):
    choice_index: int = Field(ge=0, le=15)


class AnswerOut(BaseModel):
    item_id: int
    chosen_index: int
    correct_index: int
    is_correct: bool
    explanation: str | None
    already_answered: bool
    quiz_status: QuizStatus
    answered: int
    total: int
    correct: int


class MaterialOut(BaseModel):
    id: int
    title: str | None
    snippet: str
    topic_titles: list[str]
    created_at: datetime


class MaterialPage(BaseModel):
    has_class: bool
    items: list[MaterialOut]
    next_cursor: str | None


class TeacherTopicOut(BaseModel):
    code: str
    title: str
    weak: int
    improving: int
    solid: int
    top_error_type: ErrorTypeCount | None


class TeacherSummaryOut(BaseModel):
    school_class: ClassOut | None
    students_total: int
    students_with_gaps: int | None
    topics: list[TeacherTopicOut]
