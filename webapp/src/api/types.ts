export type Role = "student" | "teacher";
export type GapStatus = "weak" | "improving" | "solid";
export type SubmissionStatus = "queued" | "processing" | "needs_confirmation" | "done" | "failed";
export type QuizStatus = "active" | "completed" | "expired";
export type QuizReason = "exam" | "review" | "manual";

export interface SchoolClass {
  id: number;
  title: string;
  grade: number | null;
}

export interface Me {
  id: number;
  first_name: string;
  last_name: string | null;
  role: Role;
  grade: number | null;
  consent_status: "none" | "pending" | "granted" | "revoked";
  school_class: SchoolClass | null;
}

export interface ErrorTypeCount {
  code: string;
  title: string;
  count: number;
}

export interface TopicGap {
  code: string;
  title: string;
  status: GapStatus;
  mistakes_total: number;
  correct_total: number;
  last_mistake_at: string | null;
  next_review_at: string | null;
  error_types: ErrorTypeCount[];
}

export interface GapMap {
  topics: TopicGap[];
  summary: Record<GapStatus, number>;
}

export interface BBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Submission {
  id: number;
  created_at: string;
  status: SubmissionStatus;
  verdict: string | null;
  topic_code: string | null;
  topic_title: string | null;
  error_type: string | null;
  error_title: string | null;
  first_error_step: number | null;
  image_url: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface Line {
  index: number;
  latex: string;
  display: string;
  confidence: number;
  bbox: BBox | null;
  is_error: boolean;
}

export interface Analysis {
  status: string | null;
  first_error_step: number | null;
  error_type: string | null;
  error_title: string | null;
  hint: string | null;
}

export interface SubmissionDetail extends Submission {
  task: string | null;
  lines: Line[];
  analysis: Analysis | null;
  error_bbox: BBox | null;
  finished_at: string | null;
}

export interface QuizSummary {
  id: number;
  reason: QuizReason;
  status: QuizStatus;
  created_at: string;
  total: number;
  answered: number;
  correct: number;
  topic_titles: string[];
}

export interface ActiveQuiz {
  quiz: QuizSummary | null;
}

export interface Choice {
  index: number;
  text: string;
}

export interface QuizItem {
  id: number;
  position: number;
  topic_code: string;
  topic_title: string;
  prompt: string;
  choices: Choice[];
  from_gap_map: boolean;
  answered_index: number | null;
  correct_index: number | null;
  is_correct: boolean | null;
}

export interface Quiz extends QuizSummary {
  items: QuizItem[];
}

export interface AnswerResult {
  item_id: number;
  chosen_index: number;
  correct_index: number;
  is_correct: boolean;
  explanation: string | null;
  already_answered: boolean;
  quiz_status: QuizStatus;
  answered: number;
  total: number;
  correct: number;
}

export interface Material {
  id: number;
  title: string | null;
  snippet: string;
  topic_titles: string[];
  created_at: string;
}

export interface MaterialPage extends Page<Material> {
  has_class: boolean;
}

export interface TeacherTopic {
  code: string;
  title: string;
  weak: number;
  improving: number;
  solid: number;
  top_error_type: ErrorTypeCount | null;
}

export interface TeacherSummary {
  school_class: SchoolClass | null;
  students_total: number;
  students_with_gaps: number | null;
  topics: TeacherTopic[];
}
