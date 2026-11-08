import json
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(180), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # student | teacher | admin
    subject = db.Column(db.String(40))  # English | Mathematics | Science
    password_hash = db.Column(db.String(255), nullable=False)
    section = db.Column(db.String(80), default="Grade 7 · Pilot Section")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    avatar_filename = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Material(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    subject_slug = db.Column(db.String(40), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    source = db.Column(db.String(20), default="teacher")  # teacher | student
    status = db.Column(db.String(20), default="pending")  # pending | approved | rejected
    filename = db.Column(db.String(255))
    extracted_text = db.Column(db.Text, default="")
    reject_reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User")
    summary = db.relationship("Summary", backref="material", uselist=False, cascade="all, delete-orphan")


class Summary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey("material.id"), nullable=False)
    intro = db.Column(db.Text, default="")
    sections_json = db.Column(db.Text, default="[]")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def sections(self):
        try:
            return json.loads(self.sections_json or "[]")
        except json.JSONDecodeError:
            return []


class Assessment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    subject_slug = db.Column(db.String(40), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey("material.id"))
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    status = db.Column(db.String(20), default="draft")  # draft | published | closed
    deadline = db.Column(db.DateTime)
    attempt_limit = db.Column(db.Integer, default=1)
    extra_attempt = db.Column(db.Boolean, default=False)
    release_scores = db.Column(db.Boolean, default=False)
    release_answers = db.Column(db.Boolean, default=False)
    release_feedback = db.Column(db.Boolean, default=False)
    difficulty = db.Column(db.String(20), default="medium")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    material = db.relationship("Material")
    questions = db.relationship("Question", backref="assessment", cascade="all, delete-orphan", order_by="Question.id")
    attempts = db.relationship("Attempt", backref="assessment", cascade="all, delete-orphan")


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessment.id"), nullable=False)
    bloom = db.Column(db.String(20), default="Analyze")
    qtype = db.Column(db.String(20), default="mcq")  # mcq | essay | problem
    prompt = db.Column(db.Text, nullable=False)
    options_json = db.Column(db.Text, default="[]")
    answer = db.Column(db.String(20))
    explanation = db.Column(db.Text, default="")
    rubric = db.Column(db.Text)
    citation = db.Column(db.String(80), default="")

    def options(self):
        try:
            return json.loads(self.options_json or "[]")
        except json.JSONDecodeError:
            return []

    def as_dict(self):
        type_labels = {"mcq": "Multiple choice", "essay": "Essay", "problem": "Problem-solving"}
        return {
            "id": self.id,
            "type": self.qtype,
            "type_label": type_labels.get(self.qtype, self.qtype),
            "bloom": self.bloom,
            "prompt": self.prompt,
            "citation": self.citation,
            "options": self.options(),
            "answer": self.answer,
            "explanation": self.explanation,
            "rubric": self.rubric,
        }


class Attempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessment.id"))
    kind = db.Column(db.String(20), nullable=False)  # assessment | practice
    subject_slug = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    attempt_no = db.Column(db.Integer, default=1)
    score_auto = db.Column(db.Integer, default=0)
    score_total_auto = db.Column(db.Integer, default=0)
    review_json = db.Column(db.Text, default="[]")
    encouragement = db.Column(db.Text, default="")
    difficulty = db.Column(db.String(20))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")

    def review_items(self):
        try:
            return json.loads(self.review_json or "[]")
        except json.JSONDecodeError:
            return []


class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(40), nullable=False)  # English | Math | Science
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, default="")
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    teacher = db.relationship("User")


class AnnouncementRead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    announcement_id = db.Column(db.Integer, db.ForeignKey("announcement.id"), nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User")
    announcement = db.relationship("Announcement")
    __table_args__ = (
        db.UniqueConstraint("user_id", "announcement_id", name="uq_announcement_read"),
    )


class Setting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(255), default="")


class SchoolYear(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=False, nullable=False)


class SchoolSection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    grade = db.Column(db.Integer, nullable=False)
    school_year_id = db.Column(db.Integer, db.ForeignKey("school_year.id"), nullable=False)
    school_year = db.relationship("SchoolYear")
    __table_args__ = (db.UniqueConstraint("name", "grade", "school_year_id", name="uq_section_grade_year"),)


class QuizDraft(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(20), default="practice")
    subject_slug = db.Column(db.String(40), nullable=False)
    material_slug = db.Column(db.String(160), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    bloom_label = db.Column(db.String(80), default="Mixed HOTS")
    difficulty = db.Column(db.String(20), default="medium")
    questions_json = db.Column(db.Text, default="[]")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def questions(self):
        try:
            return json.loads(self.questions_json or "[]")
        except json.JSONDecodeError:
            return []


class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship("User", foreign_keys=[student_id])
    teacher = db.relationship("User", foreign_keys=[teacher_id])
    messages = db.relationship(
        "ChatMessage",
        backref="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )
    __table_args__ = (db.UniqueConstraint("student_id", "teacher_id", name="uq_conversation_pair"),)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime)
    sender = db.relationship("User")
