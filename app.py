import csv
import io
import json
import logging
import os
import re
from datetime import datetime, timedelta
from functools import wraps

from urllib.parse import urlencode

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from sqlalchemy import inspect as sa_inspect, or_, text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from ai import generate_hots_questions, last_ai_error, summarize_material
from csrf import init_csrf
from extract import ExtractError, extract_text
from models import (
    Announcement,
    AnnouncementRead,
    Assessment,
    Attempt,
    ChatMessage,
    Conversation,
    Material,
    Question,
    QuizDraft,
    Setting,
    Summary,
    User,
    db,
)


def load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

logger = logging.getLogger("bloom")

BLOOM_ENV = os.environ.get("BLOOM_ENV", "development").strip().lower()
IS_PRODUCTION = BLOOM_ENV == "production"
DEV_SECRET_FALLBACK = "capstone-dev-secret-change-in-production"
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if IS_PRODUCTION:
    if not SECRET_KEY or SECRET_KEY == DEV_SECRET_FALLBACK:
        raise RuntimeError("Set a strong SECRET_KEY when BLOOM_ENV=production.")
else:
    SECRET_KEY = SECRET_KEY or DEV_SECRET_FALLBACK

def database_uri() -> str:
    """Postgres when DATABASE_URL is set (Railway / local pgAdmin); else SQLite."""
    test_path = os.environ.get("BLOOM_TEST_DB", "").strip()
    if test_path:
        return "sqlite:///" + test_path
    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or ""
    ).strip()
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        if "sslmode=" not in url.lower() and "railway" in url.lower():
            url += ("&" if "?" in url else "?") + "sslmode=require"
        return url
    path = os.path.join(app.instance_path, "bloom.db")
    return "sqlite:///" + path


app = Flask(__name__)
app.secret_key = SECRET_KEY
os.makedirs(app.instance_path, exist_ok=True)
app.config["SQLALCHEMY_DATABASE_URI"] = database_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = os.path.join(app.instance_path, "uploads")
# Used when "Keep me signed in" is checked. Without it, the session lasts until the browser closes.
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=14)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION or os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {
    "1",
    "true",
    "yes",
}
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
app.config["AVATAR_FOLDER"] = os.path.join(app.instance_path, "avatars")
os.makedirs(app.config["AVATAR_FOLDER"], exist_ok=True)
db.init_app(app)
init_csrf(app)


def show_pilot_accounts() -> bool:
    flag = os.environ.get("BLOOM_SHOW_PILOTS", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    if flag in {"0", "false", "no"}:
        return False
    return not IS_PRODUCTION and app.secret_key == DEV_SECRET_FALLBACK


def can_view_attempt(user: dict, attempt: Attempt) -> bool:
    if not user or not attempt:
        return False
    if attempt.user_id == user["id"]:
        return True
    if user["role"] == "admin":
        return True
    if user["role"] == "teacher":
        slug = teacher_subject_slug(user)
        return bool(slug and attempt.subject_slug == slug)
    return False



@app.context_processor
def inject_session_meta():
    expires_at = None
    if session.get("user_id") and session.permanent:
        expires_at = int((datetime.utcnow() + app.permanent_session_lifetime).timestamp())
    return {"session_expires_at": expires_at}


@app.context_processor
def inject_unread_messages():
    user = current_user()
    if not user:
        return {"unread_messages": 0}
    return {"unread_messages": unread_message_count(user["id"])}


@app.context_processor
def inject_announcement_unread():
    """Keep topbar/sidebar announcement badges + bell preview honest on every student page."""
    user = current_user()
    if not user or user.get("role") != "student":
        return {"unread_announcements": 0, "announcements_preview": []}
    ctx = announcements_context(user)
    return {
        "unread_announcements": ctx["unread_announcements"],
        "announcements_preview": ctx["announcements_preview"],
    }


@app.context_processor
def inject_difficulty_helpers():
    return {"difficulty_label": difficulty_label}


SUBJECTS = {
    "english": {"slug": "english", "name": "English", "announce": "English"},
    "mathematics": {"slug": "mathematics", "name": "Mathematics", "announce": "Math"},
    "science": {"slug": "science", "name": "Science", "announce": "Science"},
}

DIFFICULTIES = {
    "easy": {
        "key": "easy",
        "label": "Easy",
        "hint": "Build your understanding with more approachable questions.",
    },
    "medium": {
        "key": "medium",
        "label": "Medium",
        "hint": "Practice with a balanced level of challenge.",
    },
    "hard": {
        "key": "hard",
        "label": "Hard",
        "hint": "Challenge yourself with more complex problems.",
    },
}


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return value or "item"


def normalize_difficulty(value: str | None) -> str:
    key = (value or "").strip().lower()
    return key if key in DIFFICULTIES else "medium"


def subject_slug_from_name(name: str | None) -> str:
    if not name:
        return "general"
    needle = name.strip().lower()
    for slug, meta in SUBJECTS.items():
        if meta["name"].lower() == needle or meta["announce"].lower() == needle:
            return slug
    return "general"


def difficulty_label(value: str | None) -> str:
    return DIFFICULTIES[normalize_difficulty(value)]["label"]


PRACTICE_COUNT_MIN = 1
PRACTICE_COUNT_MAX = 15


def clamp_practice_count(value, default: int = 3) -> int:
    """Store practice item count as a plain int in [1, 15]."""
    try:
        return max(PRACTICE_COUNT_MIN, min(int(value), PRACTICE_COUNT_MAX))
    except (TypeError, ValueError):
        return default


def practice_setup_url(subject_slug, material_slug, difficulty="medium", focus="mixed", count=3, types=None):
    base = url_for("practice_setup", subject_slug=subject_slug, material_slug=material_slug)
    pairs = [
        ("difficulty", normalize_difficulty(difficulty)),
        ("focus", focus or "mixed"),
        ("count", str(clamp_practice_count(count))),
    ]
    for item in types or []:
        pairs.append(("types", item))
    return f"{base}?{urlencode(pairs)}"


def ensure_schema():
    inspector = sa_inspect(db.engine)
    tables = set(inspector.get_table_names())
    additions = (
        ("quiz_draft", "difficulty", "VARCHAR(20) DEFAULT 'medium'"),
        ("attempt", "difficulty", "VARCHAR(20)"),
        ("assessment", "difficulty", "VARCHAR(20)"),
        ("user", "avatar_filename", "VARCHAR(255)"),
    )
    preparer = db.engine.dialect.identifier_preparer
    with db.engine.begin() as conn:
        for table, column, ddl in additions:
            if table not in tables:
                continue
            columns = {col["name"] for col in inspector.get_columns(table)}
            if column not in columns:
                conn.execute(
                    text(
                        f"ALTER TABLE {preparer.quote(table)} "
                        f"ADD COLUMN {preparer.quote(column)} {ddl}"
                    )
                )


def unique_slug(base: str, model, field="slug") -> str:
    slug = slugify(base)
    candidate = slug
    index = 2
    while model.query.filter_by(**{field: candidate}).first():
        candidate = f"{slug}-{index}"
        index += 1
    return candidate


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = db.session.get(User, user_id)
    if not user:
        session.clear()
        return None
    return session_user_payload(user)


def require_user():
    user = current_user()
    if not user:
        flash("Please sign in to continue.", "danger")
        return None
    return user


def require_role(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = require_user()
            if not user:
                return redirect(url_for("login"))
            if user["role"] not in roles:
                flash("You do not have access to that page.", "danger")
                return redirect(url_for("home"))
            return fn(user, *args, **kwargs)

        return wrapper

    return decorator


def teacher_subject_slug(user) -> str:
    name = user.get("subject") or "Science"
    for slug, meta in SUBJECTS.items():
        if meta["name"] == name:
            return slug
    return "science"


def teacher_nav():
    return [
        {"label": "Home", "endpoint": "teacher_home", "key": "home"},
        {"label": "Messages", "endpoint": "messages_inbox", "key": "messages"},
        {"label": "Materials", "endpoint": "teacher_materials", "key": "materials"},
        {"label": "HOTS", "endpoint": "teacher_hots", "key": "hots"},
        {"label": "Monitor", "endpoint": "teacher_monitor", "key": "monitor"},
        {"label": "Announce", "endpoint": "teacher_announce", "key": "announce"},
        {"label": "Profile", "endpoint": "profile", "key": "profile"},
    ]


def assessments_awaiting_release(subject_slug: str) -> list:
    """Assessments with submissions that still need release — same flags/attempt filter as Monitor panels."""
    awaiting = []
    for assessment in Assessment.query.filter_by(subject_slug=subject_slug).order_by(
        Assessment.created_at.desc()
    ):
        # Same filter as teacher_monitor panel building.
        submitted = Attempt.query.filter_by(
            assessment_id=assessment.id, kind="assessment"
        ).count()
        if not submitted:
            continue
        if (
            not assessment.release_scores
            or not assessment.release_answers
            or not assessment.release_feedback
        ):
            awaiting.append(assessment)
    return awaiting


def admin_nav():
    return [
        {"label": "Home", "endpoint": "admin_home", "key": "home"},
        {"label": "Users", "endpoint": "admin_users", "key": "users"},
        {"label": "Section", "endpoint": "admin_section", "key": "section"},
        {"label": "Monitor", "endpoint": "admin_reports", "key": "reports"},
        {"label": "Settings", "endpoint": "admin_settings", "key": "settings"},
    ]


def announcement_read_ids(user_id: int) -> set[int]:
    return {
        row.announcement_id
        for row in AnnouncementRead.query.filter_by(user_id=user_id).all()
    }


def unread_announcement_count(user_id: int) -> int:
    read_ids = announcement_read_ids(user_id)
    query = Announcement.query
    if read_ids:
        query = query.filter(~Announcement.id.in_(read_ids))
    return query.count()


def mark_announcement_read(user_id: int, announcement_id: int) -> bool:
    announcement = db.session.get(Announcement, announcement_id)
    if not announcement:
        return False
    existing = AnnouncementRead.query.filter_by(
        user_id=user_id, announcement_id=announcement_id
    ).first()
    if existing:
        return True
    try:
        db.session.add(AnnouncementRead(user_id=user_id, announcement_id=announcement_id))
        db.session.commit()
    except Exception:
        db.session.rollback()
        if AnnouncementRead.query.filter_by(user_id=user_id, announcement_id=announcement_id).first():
            return True
        return False
    return True


def mark_all_announcements_read(user_id: int) -> int:
    notes = Announcement.query.all()
    read_ids = announcement_read_ids(user_id)
    pending = [note.id for note in notes if note.id not in read_ids]
    if not pending:
        return 0
    now = datetime.utcnow()
    for announcement_id in pending:
        db.session.add(AnnouncementRead(user_id=user_id, announcement_id=announcement_id, read_at=now))
    try:
        db.session.commit()
        return len(pending)
    except Exception:
        db.session.rollback()
        added = 0
        for announcement_id in pending:
            if mark_announcement_read(user_id, announcement_id):
                added += 1
        return added


def wants_json_response() -> bool:
    return request.headers.get("X-Requested-With") == "fetch"


def selected_announcement_payload(item: dict) -> dict:
    return {
        "id": item["id"],
        "title": item["title"],
        "subject": item["subject"],
        "teacher": item["teacher"],
        "posted": item["posted"],
        "when": item["when"],
        "body_blocks": item["body_blocks"],
        "href": item["href"],
    }


def announcements_url(announcement_id=None, filter_name="all", q="", arrive=False, view=""):
    kwargs = {}
    if filter_name and filter_name != "all":
        kwargs["filter"] = filter_name
    if q:
        kwargs["q"] = q
    if arrive:
        kwargs["arrive"] = 1
    if view:
        kwargs["view"] = view
    if announcement_id:
        return url_for("announcements", announcement_id=announcement_id, **kwargs)
    return url_for("announcements", **kwargs)


def announcement_when_label(when) -> str:
    if not when:
        return ""
    today = datetime.utcnow().date()
    day = when.date()
    clock = when.strftime("%I:%M %p").lstrip("0")
    if day == today:
        return f"Today · {clock}"
    if day == today - timedelta(days=1):
        return f"Yesterday · {clock}"
    return when.strftime("%b %d, %Y")


def announcement_bucket(when) -> str:
    if not when:
        return "earlier"
    day = when.date()
    today = datetime.utcnow().date()
    if day == today:
        return "today"
    if day == today - timedelta(days=1):
        return "yesterday"
    return "earlier"


def normalize_announcement_body(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    indents = [len(line) - len(line.lstrip(" ")) for line in lines if line.strip()]
    pad = min(indents) if indents else 0
    if pad:
        lines = [line[pad:] if line else line for line in lines]
    cleaned = []
    blank = 0
    for line in lines:
        if line.strip():
            blank = 0
            cleaned.append(line)
        else:
            blank += 1
            if blank == 1:
                cleaned.append("")
    return "\n".join(cleaned)


def announcement_body_blocks(text: str) -> list[list[str]]:
    normalized = normalize_announcement_body(text)
    if not normalized:
        return []
    blocks = []
    for chunk in re.split(r"\n\s*\n", normalized):
        lines = chunk.split("\n")
        if any(line.strip() for line in lines):
            blocks.append(lines)
    return blocks


def serialize_announcement(note, read_ids, selected_id=None, filter_name="all", q=""):
    body = normalize_announcement_body(note.body or "")
    preview = " ".join(body.split())
    if len(preview) > 90:
        cut = preview[:87]
        preview = (cut.rsplit(" ", 1)[0] if " " in cut else cut) + "…"
    teacher_name = note.teacher.name if note.teacher else "Your teacher"
    search = " ".join(
        part for part in (note.title, body, note.subject, teacher_name) if part
    ).lower()
    return {
        "id": note.id,
        "subject": note.subject,
        "title": note.title,
        "body": body,
        "body_blocks": announcement_body_blocks(body),
        "preview": preview,
        "teacher": teacher_name,
        "initials": initials(teacher_name),
        "photo_url": photo_url_for(note.teacher),
        "when": announcement_when_label(note.created_at),
        "posted": (
            f"{note.created_at.strftime('%B %d, %Y').replace(' 0', ' ')} · {note.created_at.strftime('%I:%M %p').lstrip('0')}"
            if note.created_at
            else ""
        ),
        "bucket": announcement_bucket(note.created_at),
        "search": search,
        "unread": note.id not in read_ids,
        "selected": selected_id == note.id,
        "href": announcements_url(note.id, filter_name, q),
    }


def note_matches_filter(note, filter_name, read_ids):
    if filter_name == "unread":
        return note.id not in read_ids
    if filter_name in {"English", "Math", "Science"}:
        return note.subject == filter_name
    return True


def note_matches_search(note, q: str) -> bool:
    if not q:
        return True
    haystack = " ".join(
        part
        for part in (
            note.title,
            note.body,
            note.subject,
            note.teacher.name if note.teacher else "",
        )
        if part
    ).lower()
    return q in haystack


def group_announcements(notes):
    groups = []
    for key, label in (("today", "Today"), ("yesterday", "Yesterday"), ("earlier", "Earlier")):
        items = [note for note in notes if note["bucket"] == key]
        if items:
            groups.append({"key": key, "label": label, "notes": items})
    return groups


def announcements_context(user=None):
    if not user:
        return {"announcements_preview": [], "unread_announcements": 0, "unread_messages": 0}
    read_ids = announcement_read_ids(user["id"])
    notes = Announcement.query.order_by(Announcement.created_at.desc()).all()
    unread = [note for note in notes if note.id not in read_ids]
    rest = [note for note in notes if note.id in read_ids]
    preview_notes = (unread + rest)[:6]
    preview = []
    for note in preview_notes:
        body = normalize_announcement_body(note.body or "")
        snippet = " ".join(body.split())
        if len(snippet) > 90:
            cut = snippet[:87]
            snippet = (cut.rsplit(" ", 1)[0] if " " in cut else cut) + "…"
        preview.append(
            {
                "id": note.id,
                "subject": note.subject,
                "teacher": note.teacher.name if note.teacher else "Your teacher",
                "title": note.title,
                "preview": snippet,
                "when": announcement_when_label(note.created_at),
                "unread": note.id not in read_ids,
                "href": announcements_url(note.id, arrive=True),
            }
        )
    return {
        "announcements_preview": preview,
        "unread_announcements": len(unread),
        "unread_messages": unread_message_count(user["id"]),
    }


def initials(name: str) -> str:
    parts = [part for part in (name or "B").split(" ") if part]
    if not parts:
        return "B"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


def relative_time(when) -> str:
    if not when:
        return ""
    seconds = max(0, int((datetime.utcnow() - when).total_seconds()))
    if seconds < 45:
        return "Just now"
    if seconds < 3600:
        mins = max(1, seconds // 60)
        return f"{mins} min ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    if seconds < 172800:
        return "Yesterday"
    return when.strftime("%b %d")


def unread_message_count(user_id: int) -> int:
    return (
        ChatMessage.query.join(Conversation)
        .filter(ChatMessage.sender_id != user_id)
        .filter(ChatMessage.read_at.is_(None))
        .filter(or_(Conversation.student_id == user_id, Conversation.teacher_id == user_id))
        .count()
    )


def can_access_conversation(user, conversation: Conversation) -> bool:
    if not conversation:
        return False
    if user["role"] == "student":
        return conversation.student_id == user["id"]
    if user["role"] == "teacher":
        return conversation.teacher_id == user["id"]
    return False


def get_or_create_conversation(student_id: int, teacher_id: int) -> Conversation:
    conversation = Conversation.query.filter_by(student_id=student_id, teacher_id=teacher_id).first()
    if conversation:
        return conversation
    conversation = Conversation(student_id=student_id, teacher_id=teacher_id)
    db.session.add(conversation)
    db.session.commit()
    return conversation


def mark_conversation_read(conversation: Conversation, user_id: int):
    unread = [
        message
        for message in conversation.messages
        if message.sender_id != user_id and message.read_at is None
    ]
    if not unread:
        return
    now = datetime.utcnow()
    for message in unread:
        message.read_at = now
    db.session.commit()


def serialize_message(message: ChatMessage, user_id: int) -> dict:
    mine = message.sender_id == user_id
    status = "sent"
    if mine and message.read_at:
        status = "read"
    return {
        "id": message.id,
        "body": message.body,
        "mine": mine,
        "status": status,
        "created_label": relative_time(message.created_at),
        "created_at": message.created_at.strftime("%b %d · %I:%M %p") if message.created_at else "",
    }


def conversation_preview(conversation: Conversation, user_id: int) -> dict:
    other = conversation.teacher if conversation.student_id == user_id else conversation.student
    last = conversation.messages[-1] if conversation.messages else None
    unread = sum(1 for message in conversation.messages if message.sender_id != user_id and message.read_at is None)
    subject_name = other.subject if other and other.subject else ""
    subject_slug = next(
        (slug for slug, meta in SUBJECTS.items() if meta["name"] == subject_name),
        "general",
    )
    started = bool(last)
    if started:
        preview = last.body[:90]
    else:
        preview = "No messages yet — start a private question about a lesson or assessment"
    return {
        "id": conversation.id,
        "other_id": other.id if other else 0,
        "name": other.name if other else "Unknown",
        "meta": (other.subject or other.role.title()) if other else "",
        "subject_slug": subject_slug,
        "initials": initials(other.name if other else "B"),
        "photo_url": photo_url_for(other),
        "preview": preview,
        "when": relative_time(last.created_at if last else conversation.updated_at) if started else "",
        "unread": unread,
        "started": started,
        "href": url_for("messages_thread", user_id=other.id) if other else url_for("messages_inbox"),
        "search": f"{other.name if other else ''} {subject_name} {preview}".lower(),
    }


def same_section(user, other) -> bool:
    left = (user.get("section") if isinstance(user, dict) else getattr(user, "section", None)) or ""
    right = (other.get("section") if isinstance(other, dict) else getattr(other, "section", None)) or ""
    if not left or not right:
        return True
    return left == right


def allowed_chat_partner(user, other) -> bool:
    if not other:
        return False
    if not same_section(user, other):
        return False
    if user["role"] == "student":
        return other.role == "teacher"
    if user["role"] == "teacher":
        return other.role == "student"
    return False


def find_conversation(user, other):
    if user["role"] == "student":
        return Conversation.query.filter_by(student_id=user["id"], teacher_id=other.id).first()
    return Conversation.query.filter_by(student_id=other.id, teacher_id=user["id"]).first()


def ask_teacher_context(user, subject_name: str, topic: str, draft: str | None = None):
    if not user or user["role"] != "student" or not subject_name:
        return None
    teachers = User.query.filter_by(role="teacher", subject=subject_name).order_by(User.name).all()
    teacher = next((item for item in teachers if same_section(user, item)), None) or (teachers[0] if teachers else None)
    if not teacher:
        return None
    message = draft or f"Hi, I have a question about {topic}."
    return {
        "name": teacher.name,
        "href": url_for("messages_thread", user_id=teacher.id, draft=message),
    }


def assessment_attempt_counts(user_id: int, assessment: Assessment) -> tuple[int, int]:
    """Return (taken, allowed) using the same formula as lobby / start / take / submit."""
    taken = Attempt.query.filter_by(
        user_id=user_id, assessment_id=assessment.id, kind="assessment"
    ).count()
    allowed = assessment.attempt_limit + (1 if assessment.extra_attempt else 0)
    return taken, allowed


def nearest_approved_material(subject_slug: str, at_time: datetime | None) -> Material | None:
    """Pick approved material in subject closest in time to at_time (usually attempt.submitted_at).

    TODO: Attempt should store material_id/material_slug at creation time to remove this fallback
    entirely — logged as known follow-up, not fixed here (schema change deferred past defense).
    """
    approved = Material.query.filter_by(subject_slug=subject_slug, status="approved").all()
    if not approved:
        return None
    if not at_time:
        return max(approved, key=lambda m: m.created_at or datetime.min)
    return min(
        approved,
        key=lambda m: abs(
            ((m.created_at or at_time) - at_time).total_seconds()
        ),
    )


def session_user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "subject": user.subject,
        "section": user.section,
        "avatar_filename": user.avatar_filename,
        "avatar_url": photo_url_for(user),
    }


def bloom_progress(user_id: int, subject_slug: str) -> tuple[int, str, bool]:
    """Return average auto-scored practice/assessment score for a subject.

    This is NOT curriculum completion. Callers must label it as an average score.
    """
    attempts = Attempt.query.filter_by(user_id=user_id, subject_slug=subject_slug).all()
    if not attempts:
        return 0, "Start with a summary or Practice Check", False
    percents = []
    blooms = {"Analyze": 0, "Evaluate": 0, "Create": 0}
    for attempt in attempts:
        if attempt.score_total_auto:
            percents.append(int(100 * attempt.score_auto / attempt.score_total_auto))
        for item in attempt.review_items():
            bloom = item.get("bloom")
            if bloom in blooms and item.get("status") == "good":
                blooms[bloom] += 1
    percent = int(sum(percents) / len(percents)) if percents else 0
    if not percents:
        return 0, "Keep practicing HOTS items from approved lessons", False
    strongest = max(blooms, key=blooms.get)
    if max(blooms.values()) == 0:
        next_line = "Keep practicing HOTS items from approved lessons"
    else:
        next_line = f"Getting stronger in {strongest}"
    return percent, next_line, True


def progress_display_label(percent: int, has_progress: bool, insight: str = "") -> str:
    """Honest label for bloom_progress values (average score, not completion)."""
    if not has_progress:
        return "Not started"
    if percent <= 0:
        base = "No auto-scored items yet"
    else:
        base = f"{percent}% avg score"
    return f"{base} · {insight}" if insight else base


def build_admin_class_monitor() -> dict:
    """Section-wide student progress, HOTS strength, and class health for admin."""
    students = User.query.filter_by(role="student").order_by(User.name).all()
    teachers = User.query.filter_by(role="teacher").order_by(User.subject, User.name).all()
    attempts = Attempt.query.order_by(Attempt.submitted_at.desc()).all()

    bloom_good = {"Analyze": 0, "Evaluate": 0, "Create": 0}
    bloom_total = {"Analyze": 0, "Evaluate": 0, "Create": 0}
    subject_scores: dict[str, list[int]] = {slug: [] for slug in SUBJECTS}
    subject_attempt_counts = {slug: 0 for slug in SUBJECTS}
    student_rows = []
    active_ids = set()
    scored_percents: list[int] = []

    attempts_by_user: dict[int, list[Attempt]] = {}
    for attempt in attempts:
        attempts_by_user.setdefault(attempt.user_id, []).append(attempt)
        subject_attempt_counts[attempt.subject_slug] = subject_attempt_counts.get(attempt.subject_slug, 0) + 1
        percent = attempt_score_percent(attempt)
        if percent is not None and attempt.subject_slug in subject_scores:
            subject_scores[attempt.subject_slug].append(percent)
            scored_percents.append(percent)
        for item in attempt.review_items():
            bloom = item.get("bloom")
            if bloom in bloom_total:
                bloom_total[bloom] += 1
                if item.get("status") == "good":
                    bloom_good[bloom] += 1

    week_ago = datetime.utcnow() - timedelta(days=7)
    recent_attempts = sum(1 for a in attempts if a.submitted_at and a.submitted_at >= week_ago)

    for student in students:
        user_attempts = attempts_by_user.get(student.id, [])
        if user_attempts:
            active_ids.add(student.id)
        percents = []
        blooms = {"Analyze": 0, "Evaluate": 0, "Create": 0}
        for attempt in user_attempts:
            percent = attempt_score_percent(attempt)
            if percent is not None:
                percents.append(percent)
            for item in attempt.review_items():
                bloom = item.get("bloom")
                if bloom in blooms and item.get("status") == "good":
                    blooms[bloom] += 1
        avg = int(round(sum(percents) / len(percents))) if percents else None
        strongest = max(blooms, key=blooms.get) if max(blooms.values()) > 0 else None
        if not user_attempts:
            status = "not_started"
            status_label = "Not started"
        elif avg is None:
            status = "warming"
            status_label = "Started · no auto score yet"
        elif avg < 50:
            status = "needs_support"
            status_label = "Needs support"
        elif avg >= 80:
            status = "strong"
            status_label = "Strong"
        else:
            status = "on_track"
            status_label = "On track"
        last = user_attempts[0] if user_attempts else None
        student_rows.append(
            {
                "id": student.id,
                "name": student.name,
                "email": student.email,
                "attempt_count": len(user_attempts),
                "practice_count": sum(1 for a in user_attempts if a.kind == "practice"),
                "assessment_count": sum(1 for a in user_attempts if a.kind == "assessment"),
                "avg_score": avg,
                "strongest_bloom": strongest,
                "status": status,
                "status_label": status_label,
                "last_title": last.title if last else "—",
                "last_when": relative_time(last.submitted_at) if last and last.submitted_at else "No activity yet",
                "photo_url": url_for("user_photo", user_id=student.id) if student.avatar_filename else None,
                "initials": "".join(part[:1] for part in (student.name or "S").split()[:2]).upper(),
            }
        )

    student_count = len(students) or 1
    active_count = len(active_ids)
    inactive_count = max(0, len(students) - active_count)
    class_avg = int(round(sum(scored_percents) / len(scored_percents))) if scored_percents else None
    needs_support = sum(1 for row in student_rows if row["status"] in {"needs_support", "not_started"})
    on_track = sum(1 for row in student_rows if row["status"] in {"on_track", "strong"})

    subject_bars = []
    for slug, meta in SUBJECTS.items():
        scores = subject_scores.get(slug) or []
        subject_bars.append(
            {
                "slug": slug,
                "name": meta["name"],
                "avg": int(round(sum(scores) / len(scores))) if scores else 0,
                "has_data": bool(scores),
                "attempts": subject_attempt_counts.get(slug, 0),
            }
        )

    bloom_rates = {}
    for key in bloom_total:
        total = bloom_total[key]
        bloom_rates[key] = int(round(100 * bloom_good[key] / total)) if total else 0

    if not students:
        insight = "Import students to begin class monitoring."
    elif active_count == 0:
        insight = "No student activity yet. Encourage teachers to publish materials and assessments."
    elif needs_support > on_track:
        insight = (
            f"{needs_support} student(s) need attention (not started or low scores). "
            "Ask subject teachers to nudge Study → Practice before HOTS assessments."
        )
    else:
        insight = (
            f"{on_track} student(s) are on track or strong. "
            f"HOTS focus: Analyze {bloom_rates['Analyze']}% · Evaluate {bloom_rates['Evaluate']}% · Create {bloom_rates['Create']}% correct on scored items."
        )

    charts = {
        "hots": {
            "labels": ["Analyze", "Evaluate", "Create"],
            "good": [bloom_good["Analyze"], bloom_good["Evaluate"], bloom_good["Create"]],
            "total": [bloom_total["Analyze"], bloom_total["Evaluate"], bloom_total["Create"]],
        },
        "subjects": {
            "labels": [bar["name"] for bar in subject_bars],
            "averages": [bar["avg"] for bar in subject_bars],
        },
        "participation": {
            "labels": ["Active", "Not started"],
            "values": [active_count, inactive_count],
        },
        "status": {
            "labels": ["Strong", "On track", "Needs support", "Not started"],
            "values": [
                sum(1 for row in student_rows if row["status"] == "strong"),
                sum(1 for row in student_rows if row["status"] == "on_track"),
                sum(1 for row in student_rows if row["status"] == "needs_support"),
                sum(1 for row in student_rows if row["status"] == "not_started"),
            ],
        },
    }

    return {
        "section_label": "Grade 7 · Pilot Section",
        "student_count": len(students),
        "teacher_count": len(teachers),
        "teacher_names": ", ".join(
            f"{t.subject or 'Teacher'} ({t.name})" for t in teachers
        )
        or "No teachers yet",
        "active_count": active_count,
        "active_percent": int(round(100 * active_count / student_count)),
        "inactive_count": inactive_count,
        "class_avg": class_avg,
        "total_attempts": len(attempts),
        "recent_attempts": recent_attempts,
        "published_assessments": Assessment.query.filter_by(status="published").count(),
        "approved_materials": Material.query.filter_by(status="approved").count(),
        "needs_support_count": needs_support,
        "on_track_count": on_track,
        "bloom_good": bloom_good,
        "bloom_total": bloom_total,
        "bloom_rates": bloom_rates,
        "subject_bars": subject_bars,
        "student_rows": student_rows,
        "insight": insight,
        "charts_json": json.dumps(charts),
    }


def lesson_review_href(subject_slug: str, material: Material | None = None) -> str:
    """Prefer the lesson summary; fall back to the subject Study tab."""
    if material and material.status == "approved" and material.summary:
        return url_for("summary_reader", slug=subject_slug, material_slug=material.slug)
    return url_for("subject_hub", slug=subject_slug, tab="study")


def build_today(user_id: int) -> list[dict]:
    """Home Today queue: Learn → Practice → Assess → Improve (calm CTAs).

    Assessments due after tomorrow are reserved for the Home “Coming up” section
    so Today stays focused on near-term work.
    """
    learn_assess: list[dict] = []
    practice_items: list[dict] = []
    improve_items: list[dict] = []
    upload_items: list[dict] = []
    now = datetime.utcnow()
    tomorrow = (now + timedelta(days=1)).date()

    for assessment in Assessment.query.filter_by(status="published").all():
        if assessment.deadline and assessment.deadline < now:
            continue
        # Farther deadlines belong in Coming up, not Today.
        if assessment.deadline and assessment.deadline.date() > tomorrow:
            continue
        taken = Attempt.query.filter_by(
            user_id=user_id, assessment_id=assessment.id, kind="assessment"
        ).count()
        limit = assessment.attempt_limit if assessment.attempt_limit is not None else 1
        allowed = limit + (1 if assessment.extra_attempt else 0)
        if taken >= allowed:
            continue
        due = "Waiting for you"
        if assessment.deadline:
            if assessment.deadline.date() == tomorrow:
                due = "Due tomorrow"
            elif assessment.deadline.date() == now.date():
                due = "Due today"
        attempt_label = "1 attempt" if allowed == 1 else f"{allowed} attempts"
        material = db.session.get(Material, assessment.material_id) if assessment.material_id else None
        review_href = lesson_review_href(assessment.subject_slug, material)
        actions = [
            {
                "label": "Review lesson",
                "href": review_href,
                "tone": "primary",
                "step": "1",
            }
        ]
        if material and material.status == "approved":
            actions.append(
                {
                    "label": "Practice",
                    "href": url_for(
                        "practice_setup",
                        subject_slug=assessment.subject_slug,
                        material_slug=material.slug,
                    ),
                    "tone": "soft",
                    "step": "2",
                }
            )
        actions.append(
            {
                "label": "Start assessment",
                "href": url_for("assessment_lobby", slug=assessment.slug),
                "tone": "accent",
                "step": str(len(actions) + 1),
            }
        )
        learn_assess.append(
            {
                "type": "assessment",
                "priority": "primary",
                "subject": SUBJECTS[assessment.subject_slug]["name"],
                "subject_slug": assessment.subject_slug,
                "kicker": due,
                "title": assessment.title,
                "meta": f"{attempt_label} · Go in order: review, practice, then assess when ready",
                "action": actions[0]["label"],
                "href": actions[0]["href"],
                "actions": actions,
            }
        )

    approved = Material.query.filter_by(status="approved").order_by(Material.created_at.desc()).first()
    if approved:
        practice_actions = [
            {
                "label": "Review lesson",
                "href": lesson_review_href(approved.subject_slug, approved),
                "tone": "primary",
                "step": "1",
            },
            {
                "label": "Practice",
                "href": url_for(
                    "practice_setup",
                    subject_slug=approved.subject_slug,
                    material_slug=approved.slug,
                ),
                "tone": "accent",
                "step": "2",
            },
        ]
        practice_items.append(
            {
                "type": "practice",
                "priority": "secondary",
                "subject": SUBJECTS[approved.subject_slug]["name"],
                "subject_slug": approved.subject_slug,
                "kicker": "Practice reminder",
                "title": f"Try the {approved.title} Practice Check",
                "meta": "Review the lesson, then take a short practice check",
                "action": practice_actions[0]["label"],
                "href": practice_actions[0]["href"],
                "actions": practice_actions,
            }
        )

    latest = (
        Attempt.query.filter_by(user_id=user_id, kind="assessment")
        .order_by(Attempt.submitted_at.desc())
        .first()
    )
    if latest:
        improve_items.append(
            {
                "type": "result",
                "priority": "secondary",
                "subject": SUBJECTS.get(latest.subject_slug, {}).get("name", ""),
                "subject_slug": latest.subject_slug or "general",
                "kicker": "Result ready",
                "title": latest.title,
                "meta": "Review answers and explanations when you feel ready",
                "action": "Review result",
                "href": url_for("attempt_review", attempt_id=latest.id),
            }
        )

    pending = Material.query.filter_by(owner_id=user_id, source="student", status="pending").first()
    if pending:
        upload_items.append(
            {
                "type": "upload",
                "priority": "secondary",
                "subject": SUBJECTS[pending.subject_slug]["name"],
                "subject_slug": pending.subject_slug,
                "kicker": "Backup upload",
                "title": f"{pending.title} is waiting for approval",
                "meta": "Your teacher will review before practice unlocks",
                "action": "See status",
                "href": url_for("subject_hub", slug=pending.subject_slug, tab="study"),
            }
        )

    # Learn/Assess (review-first cards) → Practice → Improve → Upload status
    return (learn_assess + practice_items + improve_items + upload_items)[:5]


def build_coming_up(user_id: int) -> list[dict]:
    """Upcoming published assessments with real future deadlines (after tomorrow)."""
    now = datetime.utcnow()
    tomorrow = (now + timedelta(days=1)).date()
    items: list[dict] = []
    published = Assessment.query.filter_by(status="published").order_by(Assessment.deadline.asc()).all()
    for assessment in published:
        if not assessment.deadline or assessment.deadline < now:
            continue
        if assessment.deadline.date() <= tomorrow:
            continue
        taken = Attempt.query.filter_by(
            user_id=user_id, assessment_id=assessment.id, kind="assessment"
        ).count()
        limit = assessment.attempt_limit if assessment.attempt_limit is not None else 1
        allowed = limit + (1 if assessment.extra_attempt else 0)
        if taken >= allowed:
            continue
        items.append(
            {
                "title": assessment.title,
                "subject": SUBJECTS.get(assessment.subject_slug, {}).get("name", ""),
                "due_label": assessment.deadline.strftime("Due %b %d"),
                "href": url_for("assessment_lobby", slug=assessment.slug),
                "action": "Open assessment",
            }
        )
        if len(items) >= 3:
            break
    return items


def build_recent_feedback(user_id: int, exclude_titles: set[str] | None = None) -> list[dict]:
    """Recently submitted work that already has reviewable feedback."""
    exclude_titles = exclude_titles or set()
    items: list[dict] = []
    attempts = (
        Attempt.query.filter_by(user_id=user_id)
        .order_by(Attempt.submitted_at.desc())
        .limit(12)
        .all()
    )
    for attempt in attempts:
        if attempt.title in exclude_titles:
            continue
        if attempt.kind == "assessment":
            assessment = attempt.assessment
            if not assessment or not assessment.release_scores or not assessment.release_feedback:
                continue
        summary = attempt_meta(attempt)
        items.append(
            {
                "title": attempt.title,
                "subject": SUBJECTS.get(attempt.subject_slug, {}).get("name", ""),
                "kind": "Practice" if attempt.kind == "practice" else "Assessment",
                "summary": summary,
                "href": url_for("attempt_review", attempt_id=attempt.id),
                "action": "Review feedback",
            }
        )
        if len(items) >= 2:
            break
    return items


def score_answers(questions: list[dict], form) -> tuple[list[dict], int, int, str]:
    review_items = []
    earned = 0
    auto_total = 0
    for q in questions:
        raw = (form.get(f"q{q['id']}") or "").strip()
        if q["type"] == "mcq":
            auto_total += 1
            option_map = {opt["id"]: opt["text"] for opt in q.get("options") or []}
            your_answer = option_map.get(raw, raw or "(No answer)")
            correct_answer = option_map.get(q.get("answer"))
            if raw == q.get("answer"):
                earned += 1
                status, status_label = "good", "Good job"
            else:
                status, status_label = "improve", "Let’s improve"
        else:
            your_answer = raw or "(No answer)"
            correct_answer = None
            if raw:
                status, status_label = "review", "Teacher-style review"
            else:
                status, status_label = "improve", "Try again next time"
        review_items.append(
            {
                "bloom": q.get("bloom"),
                "prompt": q.get("prompt"),
                "your_answer": your_answer,
                "correct_answer": correct_answer,
                "explanation": q.get("explanation"),
                "rubric": q.get("rubric"),
                "citation": q.get("citation"),
                "status": status,
                "status_label": status_label,
            }
        )
    unanswered = sum(1 for item in review_items if item["your_answer"] == "(No answer)")
    if auto_total:
        score_label = f"{earned}/{auto_total} automatic items"
        if unanswered == len(review_items):
            encouragement = "No answers were submitted. Review the items below, then try another practice when you are ready."
        elif earned == auto_total and unanswered == 0:
            encouragement = "Great focus on the multiple-choice items. Review the open answers to grow more."
        elif earned == 0:
            encouragement = "Let's review together. Check the explanations below, then try again on the parts that felt hard."
        else:
            encouragement = "Good effort. Review 1–2 items below to strengthen your HOTS skills."
    else:
        score_label = "Open response practice"
        if unanswered == len(review_items):
            encouragement = "No answers were submitted. Use the explanations and rubric notes, then try again."
        else:
            encouragement = "Open answers are for learning. Use the explanations and rubric notes to improve."
    return review_items, earned, auto_total, encouragement


def save_file(file_storage) -> tuple[str, bytes]:
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        raise ExtractError("Please choose a file to upload.")
    data = file_storage.read()
    if len(data) > 20 * 1024 * 1024:
        raise ExtractError("Files are limited to 20 MB.")
    return filename, data


def create_material(title, subject_slug, owner_id, source, filename, data) -> Material:
    text = extract_text(filename, data)
    stored = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], stored)
    with open(path, "wb") as handle:
        handle.write(data)
    material = Material(
        slug=unique_slug(title or filename, Material),
        title=(title or "").strip() or path_stem(filename),
        subject_slug=subject_slug,
        owner_id=owner_id,
        source=source,
        status="pending",
        filename=stored,
        extracted_text=text,
    )
    db.session.add(material)
    db.session.flush()
    try:
        attach_summary(material)
    except Exception:
        logger.exception("Could not summarize material %s", material.id)
    db.session.commit()
    return material


def path_stem(filename: str) -> str:
    return os.path.splitext(filename)[0].replace("_", " ").replace("-", " ").title()


AVATAR_MAX_BYTES = 2 * 1024 * 1024
AVATAR_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def photo_url_for(user) -> str | None:
    if not user:
        return None
    if isinstance(user, dict):
        if user.get("avatar_url"):
            return user["avatar_url"]
        user_id = user.get("id")
        filename = user.get("avatar_filename")
    else:
        user_id = getattr(user, "id", None)
        filename = getattr(user, "avatar_filename", None)
    if not user_id or not filename:
        return None
    # Skip broken DB filenames so templates fall back to initials.
    if not avatar_file_path(filename):
        return None
    return url_for("user_photo", user_id=user_id)


def avatar_extension(filename: str, data: bytes) -> str:
    ext = os.path.splitext((filename or "").lower())[1]
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in AVATAR_EXTS:
        raise ExtractError("Please upload a JPG, PNG, or WEBP photo.")
    if ext == ".jpg" and not data.startswith(b"\xff\xd8\xff"):
        raise ExtractError("That file does not look like a JPG photo.")
    if ext == ".png" and not data.startswith(b"\x89PNG"):
        raise ExtractError("That file does not look like a PNG photo.")
    if ext == ".webp" and not (data.startswith(b"RIFF") and b"WEBP" in data[:16]):
        raise ExtractError("That file does not look like a WEBP photo.")
    return ext


def avatar_file_path(filename: str) -> str | None:
    if not filename:
        return None
    name = os.path.basename(filename)
    if name != filename or ".." in filename:
        return None
    path = os.path.join(app.config["AVATAR_FOLDER"], name)
    if not os.path.isfile(path):
        return None
    return path


def save_avatar(user: User, file_storage) -> None:
    filename, data = save_file(file_storage)
    if len(data) > AVATAR_MAX_BYTES:
        raise ExtractError("Photos are limited to 2 MB.")
    ext = avatar_extension(filename, data)
    stored = f"{user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{ext}"
    path = os.path.join(app.config["AVATAR_FOLDER"], stored)
    with open(path, "wb") as handle:
        handle.write(data)
    old = user.avatar_filename
    user.avatar_filename = stored
    if old:
        old_path = avatar_file_path(old)
        if old_path:
            os.remove(old_path)


def remove_avatar(user: User) -> None:
    old_path = avatar_file_path(user.avatar_filename)
    user.avatar_filename = None
    if old_path:
        os.remove(old_path)


def attempt_meta(attempt: Attempt) -> str:
    date_label = attempt.submitted_at.strftime("%b %d") if attempt.submitted_at else "Recent"
    if (
        attempt.kind == "assessment"
        and attempt.assessment
        and not attempt.assessment.release_scores
    ):
        return f"{date_label} · Score pending release"
    if attempt.score_total_auto:
        return f"{date_label} · {attempt.score_auto}/{attempt.score_total_auto} correct"
    return f"{date_label} · Not auto-scored"


def attempt_score_percent(attempt: Attempt) -> int | None:
    if not attempt.score_total_auto:
        return None
    return int(round(100 * attempt.score_auto / attempt.score_total_auto))


def assessment_score_tone(percent: int | None) -> str:
    if percent is None:
        return "pending"
    if percent >= 80:
        return "high"
    if percent >= 50:
        return "mid"
    return "low"


def format_trend(current: int | None, previous: int | None) -> dict | None:
    if current is None or previous is None:
        return None
    delta = current - previous
    if delta == 0:
        return {"direction": "flat", "label": "Same as last"}
    if delta > 0:
        return {"direction": "up", "label": f"↑ +{delta}% vs last"}
    return {"direction": "down", "label": f"↓ −{abs(delta)}% vs last"}


def attach_summary(material: Material):
    payload = summarize_material(material.title, material.extracted_text, SUBJECTS[material.subject_slug]["name"])
    summary = material.summary or Summary(material_id=material.id)
    summary.intro = payload["intro"]
    summary.sections_json = json.dumps(payload["sections"])
    db.session.add(summary)


def stored_filename_label(filename: str) -> str:
    if not filename:
        return "Pasted text"
    name = os.path.basename(filename)
    if len(name) > 15 and name[14] == "_" and name[:14].isdigit():
        return name[15:] or name
    return name


def material_file_path(material: Material) -> str | None:
    if not material or not material.filename:
        return None
    name = os.path.basename(material.filename)
    if name != material.filename or ".." in material.filename:
        return None
    path = os.path.join(app.config["UPLOAD_FOLDER"], name)
    if not os.path.isfile(path):
        return None
    return path


def teacher_owned_material(user, material_id: int) -> Material | None:
    slug = teacher_subject_slug(user)
    material = db.session.get(Material, material_id)
    if not material or material.subject_slug != slug:
        return None
    return material


def section_students_for(user) -> list[User]:
    students = User.query.filter_by(role="student").order_by(User.name).all()
    return [student for student in students if same_section(user, student)]


def deploy_material(material: Material):
    if not material.summary:
        attach_summary(material)
    material.status = "approved"
    material.reject_reason = None


def reject_material(material: Material):
    material.status = "rejected"
    material.reject_reason = "Not enough usable lesson text or not aligned to the class material."


def teacher_student_progress(user, subject_slug: str) -> list[dict]:
    rows = []
    for student in section_students_for(user):
        percent, insight, has_progress = bloom_progress(student.id, subject_slug)
        attempts = (
            Attempt.query.filter_by(user_id=student.id, subject_slug=subject_slug)
            .order_by(Attempt.submitted_at.desc())
            .all()
        )
        last = attempts[0] if attempts else None
        rows.append(
            {
                "id": student.id,
                "name": student.name,
                "initials": initials(student.name),
                "photo_url": photo_url_for(student),
                "section": student.section or "Grade 7 · Pilot Section",
                "percent": percent if has_progress else None,
                "tone": assessment_score_tone(percent if has_progress else None),
                "insight": insight if has_progress else "No attempts yet",
                "progress_label": progress_display_label(percent, has_progress, insight if has_progress else ""),
                "practice_n": sum(1 for item in attempts if item.kind == "practice"),
                "assessment_n": sum(1 for item in attempts if item.kind == "assessment"),
                "last_title": last.title if last else "No attempts yet",
                "last_when": relative_time(last.submitted_at) if last else "",
                "last_href": url_for("attempt_review", attempt_id=last.id) if last else None,
                "message_href": url_for("messages_thread", user_id=student.id),
            }
        )
    return rows


def seed():
    if IS_PRODUCTION and os.environ.get("BLOOM_SEED_DEMO", "").lower() not in {"1", "true", "yes"}:
        # Production should not invent demo passwords unless explicitly requested.
        if not db.session.get(Setting, "english_only"):
            db.session.add(Setting(key="english_only", value="yes"))
        if not db.session.get(Setting, "max_upload_mb"):
            db.session.add(Setting(key="max_upload_mb", value="20"))
        db.session.commit()
        return
    users = [
        ("student@letran-calamba.edu.ph", "Demo Student", "student", None, "student123"),
        ("teacher@letran-calamba.edu.ph", "Demo Science Teacher", "teacher", "Science", "teacher123"),
        ("english.teacher@letran-calamba.edu.ph", "Demo English Teacher", "teacher", "English", "teacher123"),
        ("math.teacher@letran-calamba.edu.ph", "Demo Math Teacher", "teacher", "Mathematics", "teacher123"),
        ("admin@letran-calamba.edu.ph", "Demo Admin", "admin", None, "admin123"),
    ]
    for email, name, role, subject, password in users:
        if User.query.filter_by(email=email).first():
            continue
        db.session.add(
            User(
                email=email,
                name=name,
                role=role,
                subject=subject,
                password_hash=generate_password_hash(password),
            )
        )
    if not db.session.get(Setting, "english_only"):
        db.session.add(Setting(key="english_only", value="yes"))
    if not db.session.get(Setting, "max_upload_mb"):
        db.session.add(Setting(key="max_upload_mb", value="20"))
    db.session.commit()
    seed_demo_content()


def seed_demo_content():
    if not Material.query.first():
        teacher = User.query.filter_by(role="teacher", subject="Science").first()
        if not teacher:
            return
        text = (
            "Ecosystems are communities of living things interacting with their environment. "
            "Producers such as plants make food through photosynthesis. Consumers eat plants or other animals. "
            "Decomposers break down dead matter and return nutrients to the soil. Energy flows from the sun to "
            "producers and then to consumers. A food chain shows one path of energy, while a food web shows many "
            "connected chains. If one part of an ecosystem is damaged, other parts can also be affected. Students "
            "should use evidence from this lesson when they explain how living things depend on one another."
        )
        material = Material(
            slug="ecosystems",
            title="Ecosystems",
            subject_slug="science",
            owner_id=teacher.id,
            source="teacher",
            status="approved",
            filename="ecosystems.txt",
            extracted_text=text,
        )
        db.session.add(material)
        db.session.flush()
        attach_summary(material)
        seed_path = os.path.join(app.config["UPLOAD_FOLDER"], os.path.basename(material.filename))
        if not os.path.isfile(seed_path):
            with open(seed_path, "w", encoding="utf-8") as handle:
                handle.write(text)
        if not Announcement.query.first():
            db.session.add(
                Announcement(
                    subject="Science",
                    title="Welcome to Bloom",
                    body="Read the Ecosystems summary, then try a Practice Check when you are ready.",
                    teacher_id=teacher.id,
                )
            )
        db.session.commit()
    material = Material.query.filter_by(slug="ecosystems").first()
    if material and material.filename:
        seed_path = os.path.join(app.config["UPLOAD_FOLDER"], os.path.basename(material.filename))
        if not os.path.isfile(seed_path) and material.extracted_text:
            with open(seed_path, "w", encoding="utf-8") as handle:
                handle.write(material.extracted_text)
    ensure_demo_assessment()
    scrub_demo_chat_messages()


def ensure_demo_assessment():
    """Ensure the pilot DB has one published Science assessment for demos."""
    if Assessment.query.filter_by(status="published").first():
        return
    teacher = User.query.filter_by(role="teacher", subject="Science").first()
    material = Material.query.filter_by(subject_slug="science", status="approved").first()
    if not teacher or not material:
        return
    assessment = Assessment(
        slug=unique_slug("ecosystems-hots-check", Assessment),
        title="Ecosystems HOTS Check",
        subject_slug="science",
        material_id=material.id,
        created_by=teacher.id,
        status="published",
        attempt_limit=1,
        extra_attempt=False,
        release_scores=True,
        release_answers=True,
        release_feedback=True,
        difficulty="medium",
    )
    db.session.add(assessment)
    db.session.flush()
    samples = [
        {
            "bloom": "Analyze",
            "qtype": "mcq",
            "prompt": "A food web in a pond loses many plants. Which outcome best follows from the lesson?",
            "options_json": json.dumps(
                [
                    {"id": "a", "text": "Only decomposers are affected"},
                    {"id": "b", "text": "Consumers that rely on those plants may struggle next"},
                    {"id": "c", "text": "Sunlight stops reaching the water"},
                    {"id": "d", "text": "Energy no longer comes from the sun"},
                ]
            ),
            "answer": "b",
            "explanation": "Producers support consumers. If plants decline, animals that depend on them can be affected.",
            "citation": "p. 1",
        },
        {
            "bloom": "Evaluate",
            "qtype": "essay",
            "prompt": "A classmate says decomposers are optional in an ecosystem. Evaluate that claim using evidence from the lesson.",
            "options_json": "[]",
            "answer": None,
            "explanation": "Decomposers return nutrients to the soil, so they support producers over time.",
            "rubric": "Claim + lesson evidence + clear judgment",
            "citation": "p. 2",
        },
        {
            "bloom": "Create",
            "qtype": "problem",
            "prompt": "Create a short Grade 7 example of a three-step food chain that starts with a producer from this lesson.",
            "options_json": "[]",
            "answer": None,
            "explanation": "A strong example starts with a producer, then a consumer, then another consumer or decomposer link.",
            "rubric": "Original example + clear producer-to-consumer order",
            "citation": "p. 3",
        },
    ]
    for sample in samples:
        db.session.add(Question(assessment_id=assessment.id, **sample))
    if not Announcement.query.filter_by(title="Ecosystems HOTS Check is open").first():
        db.session.add(
            Announcement(
                subject="Science",
                title="Ecosystems HOTS Check is open",
                body=(
                    "Your Ecosystems HOTS Check is published. Open Science → Assessments, "
                    "start when you are ready, and review feedback after you submit."
                ),
                teacher_id=teacher.id,
            )
        )
    db.session.commit()


def scrub_demo_chat_messages():
    """Replace known inappropriate demo chat fixtures in local/pilot databases."""
    if IS_PRODUCTION:
        return
    replacements = 0
    for message in ChatMessage.query.all():
        body = (message.body or "").strip()
        if not body:
            continue
        upper = body.upper()
        if "TANGINA" in upper:
            message.body = (
                "Please revise your explanation so it shows cause and effect from the lesson."
            )
            replacements += 1
    if replacements:
        db.session.commit()


with app.app_context():
    db.create_all()
    ensure_schema()
    if not os.environ.get("BLOOM_TEST_DB"):
        seed()


@app.route("/")
def index():
    if current_user():
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("home"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "1"
        user = User.query.filter_by(email=email).first()
        if user and password and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.id
            session.permanent = remember
            # Session clear drops CSRF; mint a fresh token for the next form.
            from csrf import get_csrf_token

            get_csrf_token()
            flash("Welcome to Bloom. For security, change your temporary password in Profile later.", "success")
            return redirect(url_for("home"))
        flash("School email or password is incorrect. Check your Letran email and try again.", "danger")
        return redirect(url_for("login"))
    return render_template("login.html", show_pilot_accounts=show_pilot_accounts())


@app.route("/home")
def home():
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] == "teacher":
        return redirect(url_for("teacher_home"))
    if user["role"] == "admin":
        return redirect(url_for("admin_home"))

    first_name = user["name"].split(" ")[0]
    subjects = []
    for slug, meta in SUBJECTS.items():
        percent, insight, has_progress = bloom_progress(user["id"], slug)
        teacher = User.query.filter_by(role="teacher", subject=meta["name"]).first()
        next_action = "Next: Explore approved lessons"
        published = Assessment.query.filter_by(subject_slug=slug, status="published").all()
        open_hots = False
        for assessment in published:
            taken = Attempt.query.filter_by(
                user_id=user["id"], assessment_id=assessment.id, kind="assessment"
            ).count()
            limit = assessment.attempt_limit if assessment.attempt_limit is not None else 1
            allowed = limit + (1 if assessment.extra_attempt else 0)
            if taken < allowed:
                open_hots = True
                break
        if open_hots:
            next_action = "Next: Open a HOTS Assessment"
        elif published:
            next_action = "Next: Review your last result"
        elif Material.query.filter_by(subject_slug=slug, status="approved").first():
            next_action = "Next: Read a summary or start practice"
        subjects.append(
            {
                "slug": slug,
                "name": meta["name"],
                "teacher": teacher.name if teacher else "Subject teacher",
                "progress_label": progress_display_label(percent, has_progress, insight if has_progress else ""),
                "progress_insight": insight,
                "progress_percent": percent,
                "has_progress": has_progress,
                "next_action": next_action,
            }
        )
    today = build_today(user["id"])
    announce_ctx = announcements_context(user)
    today_titles = {item.get("title") for item in today if item.get("title")}
    teacher_updates = (announce_ctx.get("announcements_preview") or [])[:2]
    coming_up = build_coming_up(user["id"])
    recent_feedback = build_recent_feedback(user["id"], exclude_titles=today_titles)
    overall = 0
    tracked = [item for item in subjects if item["has_progress"]]
    if tracked:
        overall = int(round(sum(item["progress_percent"] for item in tracked) / len(tracked)))
    has_practice_score = bool(tracked) and overall > 0
    context = {
        "user": user,
        "greeting": f"Hi, {first_name}",
        "topbar_sub": "Home",
        "guide_note": "Open a subject to keep learning — then check Today for what to do next.",
        "weekly_goal": {
            "percent": overall,
            "has_progress": has_practice_score,
            "hint": (
                "Start a summary or Practice Check to begin tracking your practice average."
                if not has_practice_score
                else "Average of auto-scored practice and assessment items across subjects."
            ),
        },
        "today_items": today,
        "subjects": subjects,
        "teacher_updates": teacher_updates,
        "coming_up": coming_up,
        "recent_feedback": recent_feedback,
    }
    context.update(announce_ctx)
    return render_template("student_home.html", **context)


@app.route("/subjects/<slug>", methods=["GET", "POST"])
def subject_hub(slug):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    meta = SUBJECTS.get(slug)
    if not meta:
        flash("That subject is not available.", "danger")
        return redirect(url_for("home"))

    if request.method == "POST" and user["role"] == "student":
        return student_backup_upload(user, slug)

    requested_tab = request.args.get("tab")

    teacher = User.query.filter_by(role="teacher", subject=meta["name"]).first()
    percent, insight, has_progress = bloom_progress(user["id"], slug)
    published = Assessment.query.filter_by(subject_slug=slug, status="published").all()
    open_hots = False
    for assessment in published:
        taken = Attempt.query.filter_by(
            user_id=user["id"], assessment_id=assessment.id, kind="assessment"
        ).count()
        limit = assessment.attempt_limit if assessment.attempt_limit is not None else 1
        allowed = limit + (1 if assessment.extra_attempt else 0)
        if taken < allowed:
            open_hots = True
            break
    if open_hots:
        next_action = "Open a HOTS Assessment when you’re ready"
    elif published:
        next_action = "Review your latest assessment result"
    elif Material.query.filter_by(subject_slug=slug, status="approved").first():
        next_action = "Read a summary, then start practice"
    else:
        next_action = "Explore approved lessons when your teacher posts them"
    subject = {
        "slug": slug,
        "name": meta["name"],
        "teacher": teacher.name if teacher else "Subject teacher",
        "progress_label": progress_display_label(percent, has_progress, insight if has_progress else ""),
        "progress_percent": percent,
        "has_progress": has_progress,
        "progress_insight": insight,
        "next_action": next_action,
    }

    now = datetime.utcnow()
    due, open_items, closed = [], [], []
    for assessment in Assessment.query.filter_by(subject_slug=slug).filter(Assessment.status != "draft"):
        taken = Attempt.query.filter_by(user_id=user["id"], assessment_id=assessment.id, kind="assessment").count()
        allowed = assessment.attempt_limit + (1 if assessment.extra_attempt else 0)
        href = url_for("assessment_lobby", slug=assessment.slug)
        entry = {
            "title": assessment.title,
            "status_label": assessment.status.title(),
            "meta": assessment.deadline.strftime("Due %b %d · %I:%M %p") if assessment.deadline else "Open assessment",
            "action": "Start now" if taken < allowed else "View",
            "href": href if taken < allowed else url_for("results", filter="assessments"),
            "primary": taken < allowed and assessment.status == "published",
        }
        if assessment.status == "closed" or (assessment.deadline and assessment.deadline < now and taken >= allowed):
            closed.append(entry)
        elif taken >= allowed:
            closed.append({**entry, "status_label": "Submitted"})
        elif assessment.deadline and assessment.deadline <= now + timedelta(days=1):
            due.append({**entry, "status_label": "Due soon — start now"})
        else:
            open_items.append(entry)

    approved = Material.query.filter_by(subject_slug=slug, status="approved").order_by(Material.created_at.desc()).all()
    materials = []
    practice_items = []
    for material in approved:
        materials.append(
            {
                "kicker": "Approved material",
                "title": material.title,
                "meta": "Summary ready · Citations included" if material.summary else "Approved for study",
                "summary_href": url_for("summary_reader", slug=slug, material_slug=material.slug),
                "practice_href": url_for("practice_setup", subject_slug=slug, material_slug=material.slug),
            }
        )
        practice_items.append(
            {
                "kicker": "Ready",
                "title": f"{material.title} Practice Check",
                "meta": "From approved lesson · Personal practice",
                "action": "Start",
                "href": url_for("practice_setup", subject_slug=slug, material_slug=material.slug),
                "locked": False,
            }
        )

    if requested_tab in {"assessments", "study", "practice", "results"}:
        tab = requested_tab
    elif materials:
        tab = "study"
    elif practice_items:
        tab = "practice"
    elif due or open_items:
        tab = "assessments"
    else:
        tab = "study"
    pending_uploads = [
        f"{item.title}"
        for item in Material.query.filter_by(subject_slug=slug, source="student", status="pending", owner_id=user["id"])
    ]
    for item in Material.query.filter_by(subject_slug=slug, source="student", status="pending"):
        if item.owner_id == user["id"]:
            practice_items.append(
                {
                    "kicker": "Waiting for approval",
                    "title": f"{item.title} practice",
                    "meta": "Backup upload pending teacher review",
                    "action": "Locked",
                    "href": "#",
                    "locked": True,
                }
            )

    result_items = []
    for attempt in Attempt.query.filter_by(user_id=user["id"], subject_slug=slug).order_by(Attempt.submitted_at.desc()):
        result_items.append(
            {
                "kicker": attempt.kind.title(),
                "title": attempt.title,
                "meta": attempt_meta(attempt),
                "action": "Review",
                "href": url_for("attempt_review", attempt_id=attempt.id),
            }
        )

    context = {
        "user": user,
        "subject": subject,
        "tab": tab,
        "assessment_groups": [
            {"label": "Due", "entries": due},
            {"label": "Open", "entries": open_items},
            {"label": "Closed", "entries": closed},
        ],
        "materials": materials,
        "pending_uploads": pending_uploads,
        "practice_items": practice_items,
        "result_items": result_items,
        "ask_teacher": ask_teacher_context(user, meta["name"], meta["name"]),
    }
    context.update(announcements_context(user))
    return render_template("subject_hub.html", **context)


def student_backup_upload(user, slug):
    title = request.form.get("title", "").strip()
    file = request.files.get("file")
    try:
        if not file:
            raise ExtractError("Please choose a Canvas file to upload.")
        filename, data = save_file(file)
        create_material(title or path_stem(filename), slug, user["id"], "student", filename, data)
        flash("Backup uploaded. Practice unlocks after your teacher reviews the summary.", "success")
    except ExtractError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("subject_hub", slug=slug, tab="study"))


@app.route("/subjects/<slug>/summaries/<material_slug>")
def summary_reader(slug, material_slug):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    meta = SUBJECTS.get(slug)
    material = Material.query.filter_by(slug=material_slug, subject_slug=slug).first()
    if not meta or not material or material.status != "approved" or not material.summary:
        flash("That summary is not available.", "danger")
        return redirect(url_for("home"))
    teacher = User.query.filter_by(role="teacher", subject=meta["name"]).first()
    context = {
        "user": user,
        "subject": {"slug": slug, "name": meta["name"], "teacher": teacher.name if teacher else ""},
        "summary": {
            "slug": material.slug,
            "title": material.title,
            "intro": material.summary.intro,
            "sections": material.summary.sections(),
        },
        "ask_teacher": ask_teacher_context(user, meta["name"], material.title),
    }
    context.update(announcements_context(user))
    return render_template("summary_reader.html", **context)


@app.route("/subjects/<subject_slug>/practice/<material_slug>")
def practice_setup(subject_slug, material_slug):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    meta = SUBJECTS.get(subject_slug)
    material = Material.query.filter_by(slug=material_slug, subject_slug=subject_slug, status="approved").first()
    if not meta or not material:
        flash("That practice setup is not available.", "danger")
        return redirect(url_for("home"))
    selected_focus = request.args.get("focus", "mixed")
    if selected_focus not in {"mixed", "c4", "c5", "c6"}:
        selected_focus = "mixed"
    selected_count = clamp_practice_count(request.args.get("count", 3))
    selected_types = request.args.getlist("types") or ["mcq", "essay", "problem"]
    selected_difficulty = normalize_difficulty(
        request.args.get("difficulty") or session.get("practice_difficulty")
    )
    session["practice_difficulty"] = selected_difficulty
    context = {
        "user": user,
        "subject": {"slug": subject_slug, "name": meta["name"]},
        "material_slug": material.slug,
        "material_title": material.title,
        "difficulties": list(DIFFICULTIES.values()),
        "selected_difficulty": selected_difficulty,
        "selected_focus": selected_focus,
        "selected_count": selected_count,
        "selected_types": selected_types,
        "back_href": url_for("summary_reader", slug=subject_slug, material_slug=material.slug)
        if material.summary
        else url_for("subject_hub", slug=subject_slug, tab="study"),
    }
    context.update(announcements_context(user))
    return render_template("practice_setup.html", **context)


@app.route("/subjects/<subject_slug>/practice/<material_slug>/take", methods=["GET", "POST"])
def practice_take(subject_slug, material_slug):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    meta = SUBJECTS.get(subject_slug)
    material = Material.query.filter_by(slug=material_slug, subject_slug=subject_slug, status="approved").first()
    if not meta or not material:
        flash("That practice check is not available.", "danger")
        return redirect(url_for("home"))

    if request.method == "POST":
        focus = request.form.get("focus", "mixed")
        types = request.form.getlist("types") or ["mcq", "essay", "problem"]
        count = clamp_practice_count(request.form.get("count", 3))
        difficulty = normalize_difficulty(request.form.get("difficulty") or session.get("practice_difficulty"))
        session["practice_difficulty"] = difficulty
        questions = generate_hots_questions(
            material.title, material.extracted_text, meta["name"], focus, count, types, difficulty
        )
        if not questions:
            flash(
                "We couldn't generate your practice right now. "
                f"Your selected difficulty: {difficulty_label(difficulty)}.",
                "danger",
            )
            return redirect(
                practice_setup_url(subject_slug, material_slug, difficulty, focus, count, types)
            )
        if last_ai_error():
            logger.warning("Practice AI fallback used: %s", last_ai_error())
            flash(
                "Bloom could not reach the AI helper, so it used basic practice questions instead. "
                "You can still submit and review your answers.",
                "danger",
            )
        bloom_label = {"mixed": "Mixed HOTS", "c4": "Analyze", "c5": "Evaluate", "c6": "Create"}.get(
            focus, "Mixed HOTS"
        )
        QuizDraft.query.filter_by(user_id=user["id"], kind="practice").delete()
        draft = QuizDraft(
            user_id=user["id"],
            kind="practice",
            subject_slug=subject_slug,
            material_slug=material_slug,
            title=material.title,
            bloom_label=bloom_label,
            difficulty=difficulty,
            questions_json=json.dumps(questions),
        )
        db.session.add(draft)
        db.session.commit()
        session["practice_draft_id"] = draft.id
        return redirect(url_for("practice_take", subject_slug=subject_slug, material_slug=material_slug))

    draft = db.session.get(QuizDraft, session.get("practice_draft_id"))
    if (
        not draft
        or draft.user_id != user["id"]
        or draft.kind != "practice"
        or draft.material_slug != material_slug
        or draft.subject_slug != subject_slug
    ):
        flash("Generate a Practice Check from the setup screen first.", "danger")
        return redirect(url_for("practice_setup", subject_slug=subject_slug, material_slug=material_slug))
    questions = draft.questions()
    if not questions:
        flash("That practice draft is empty. Please generate again.", "danger")
        return redirect(url_for("practice_setup", subject_slug=subject_slug, material_slug=material_slug))
    context = {
        "user": user,
        "subject": {"slug": subject_slug, "name": meta["name"]},
        "material_slug": material_slug,
        "material_title": material.title,
        "questions": questions,
        "bloom_label": draft.bloom_label or "Mixed HOTS",
        "difficulty_key": draft.difficulty or "medium",
        "difficulty_name": difficulty_label(draft.difficulty),
        "draft_id": draft.id,
    }
    context.update(announcements_context(user))
    return render_template("practice_take.html", **context)


@app.route("/subjects/<subject_slug>/practice/<material_slug>/submit", methods=["POST"])
def practice_submit(subject_slug, material_slug):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    draft = db.session.get(QuizDraft, session.get("practice_draft_id"))
    if not draft or draft.user_id != user["id"] or draft.material_slug != material_slug:
        flash("Please generate a Practice Check first.", "danger")
        return redirect(url_for("practice_setup", subject_slug=subject_slug, material_slug=material_slug))
    questions = draft.questions()
    review_items, earned, auto_total, encouragement = score_answers(questions, request.form)
    attempt = Attempt(
        user_id=user["id"],
        kind="practice",
        subject_slug=subject_slug,
        title=f"{draft.title} Practice Check",
        score_auto=earned,
        score_total_auto=auto_total,
        review_json=json.dumps(review_items),
        encouragement=encouragement,
        difficulty=draft.difficulty,
    )
    db.session.add(attempt)
    db.session.delete(draft)
    db.session.commit()
    session.pop("practice_draft_id", None)
    flash("Practice submitted. Review your answers below.", "success")
    return redirect(url_for("attempt_review", attempt_id=attempt.id))


@app.route("/results/<int:attempt_id>")
def attempt_review(attempt_id):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    attempt = db.session.get(Attempt, attempt_id)
    if not attempt:
        flash("That result is not available.", "danger")
        return redirect(url_for("results" if user["role"] == "student" else "home"))
    if not can_view_attempt(user, attempt):
        flash("You do not have access to that result.", "danger")
        return redirect(url_for("results" if user["role"] == "student" else "home"))
    meta = SUBJECTS.get(attempt.subject_slug, {"name": "Subject", "slug": attempt.subject_slug})
    review_items = attempt.review_items()
    score_label = (
        f"{attempt.score_auto}/{attempt.score_total_auto} automatic items"
        if attempt.score_total_auto
        else "Open response practice"
    )
    encouragement = attempt.encouragement
    unanswered = sum(1 for item in review_items if (item.get("your_answer") or "") == "(No answer)")
    if unanswered == len(review_items) and review_items:
        hero_title = "Let’s review together."
    elif attempt.score_total_auto and attempt.score_auto == 0:
        hero_title = "Let’s review and improve."
    elif attempt.score_total_auto and attempt.score_auto == attempt.score_total_auto and unanswered == 0:
        hero_title = "Nice work. Let’s review and improve."
    else:
        hero_title = "Let’s review and improve."
    assessment_exhausted = False
    if attempt.kind == "assessment" and attempt.assessment and user["role"] == "student":
        assessment = attempt.assessment
        if not assessment.release_scores:
            score_label = "Score pending release"
            encouragement = "Submitted. Your teacher controls when scores and feedback appear."
            hero_title = "Submitted. Waiting for teacher release."
        for item in review_items:
            if not assessment.release_answers:
                item["correct_answer"] = None
            if not assessment.release_feedback:
                item["explanation"] = "Feedback will follow your teacher’s release settings."
                item["rubric"] = None
            if not assessment.release_scores:
                item["status_label"] = "Submitted"
                item["status"] = "review"
        taken, allowed = assessment_attempt_counts(user["id"], assessment)
        # Closed/exhausted Improve messaging only after scores are released — pending wins otherwise
        # (same precedence as results.html's story branch).
        assessment_exhausted = taken >= allowed and assessment.release_scores
        if assessment_exhausted:
            hero_title = "This assessment is closed."

    next_steps = []
    ask_teacher = ask_teacher_context(user, meta["name"], attempt.title)
    if user["role"] == "student":
        material = None
        if attempt.assessment and attempt.assessment.material_id:
            material = db.session.get(Material, attempt.assessment.material_id)
        if not material:
            material = nearest_approved_material(attempt.subject_slug, attempt.submitted_at)
        if assessment_exhausted:
            ask_teacher = ask_teacher_context(
                user,
                meta["name"],
                attempt.title,
                draft=f"Hi, could I get an extra attempt on {attempt.title}?",
            )
            if ask_teacher:
                next_steps.append(
                    {
                        "kicker": "Assessment closed",
                        "title": "Request an extra attempt",
                        "meta": "Your teacher can reopen this HOTS check with one more try.",
                        "action": "Message teacher",
                        "href": ask_teacher["href"],
                        "primary": True,
                    }
                )
            if material:
                next_steps.append(
                    {
                        "kicker": "Practice on your own",
                        "title": f"Practice this topic: {material.title}",
                        "meta": "Separate from the closed assessment — builds understanding for next time.",
                        "action": "Practice this topic",
                        "href": url_for(
                            "practice_setup",
                            subject_slug=material.subject_slug,
                            material_slug=material.slug,
                        ),
                        "primary": False,
                    }
                )
                if material.summary:
                    next_steps.append(
                        {
                            "kicker": "Understand first",
                            "title": f"Re-read the {material.title} summary",
                            "meta": "Review key ideas while feedback is fresh.",
                            "action": "Open summary",
                            "href": url_for(
                                "summary_reader",
                                slug=material.subject_slug,
                                material_slug=material.slug,
                            ),
                            "primary": False,
                        }
                    )
            next_steps.append(
                {
                    "kicker": "Subject hub",
                    "title": f"Continue in {meta['name']}",
                    "meta": "Study or practice from one place. This HOTS assessment stays closed.",
                    "action": "Open subject",
                    "href": url_for("subject_hub", slug=attempt.subject_slug, tab="practice"),
                    "primary": False,
                }
            )
        else:
            needs_retry = unanswered > 0 or (
                attempt.score_total_auto and attempt.score_auto < attempt.score_total_auto
            )
            if material:
                next_steps.append(
                    {
                        "kicker": "Practice again" if needs_retry else "Keep going",
                        "title": f"{'Try another check on' if needs_retry else 'Practice'} {material.title}",
                        "meta": (
                            "Use the feedback above while it’s fresh."
                            if needs_retry
                            else "Another short practice builds confidence."
                        ),
                        "action": "Practice again" if needs_retry else "Start practice",
                        "href": url_for(
                            "practice_setup",
                            subject_slug=material.subject_slug,
                            material_slug=material.slug,
                        ),
                        "primary": True,
                    }
                )
                if material.summary:
                    next_steps.append(
                        {
                            "kicker": "Understand first",
                            "title": f"Re-read the {material.title} summary",
                            "meta": "Review key ideas, then try another practice.",
                            "action": "Open summary",
                            "href": url_for(
                                "summary_reader",
                                slug=material.subject_slug,
                                material_slug=material.slug,
                            ),
                            "primary": False,
                        }
                    )
            next_steps.append(
                {
                    "kicker": "Subject hub",
                    "title": f"Continue in {meta['name']}",
                    "meta": "Study, practice, or open assessments from one place.",
                    "action": "Open subject",
                    "href": url_for("subject_hub", slug=attempt.subject_slug, tab="practice"),
                    "primary": False,
                }
            )

    improve_count = sum(1 for item in review_items if item.get("status") == "improve")
    good_count = sum(1 for item in review_items if item.get("status") == "good")
    context = {
        "user": user,
        "subject": {"name": meta["name"], "slug": attempt.subject_slug},
        "material_title": attempt.title,
        "score_label": score_label,
        "encouragement": encouragement,
        "hero_title": hero_title,
        "review_items": review_items,
        "ask_teacher": ask_teacher,
        "assessment_exhausted": assessment_exhausted,
        "difficulty_name": difficulty_label(attempt.difficulty) if attempt.difficulty else None,
        "kind": attempt.kind,
        "next_steps": next_steps,
        "story_summary": {
            "good": good_count,
            "improve": improve_count,
            "total": len(review_items),
        },
    }
    context.update(announcements_context(user))
    return render_template("practice_result.html", **context)


@app.route("/assessments/<slug>")
def assessment_lobby(slug):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    assessment = Assessment.query.filter_by(slug=slug).first()
    if not assessment or assessment.status == "draft":
        flash("That assessment is not available.", "danger")
        return redirect(url_for("home"))
    taken = Attempt.query.filter_by(user_id=user["id"], assessment_id=assessment.id, kind="assessment").count()
    allowed = assessment.attempt_limit + (1 if assessment.extra_attempt else 0)
    material = db.session.get(Material, assessment.material_id) if assessment.material_id else None
    review_href = lesson_review_href(assessment.subject_slug, material)
    context = {
        "user": user,
        "assessment": {
            "slug": assessment.slug,
            "subject_slug": assessment.subject_slug,
            "subject": SUBJECTS[assessment.subject_slug]["name"],
            "title": assessment.title,
            "deadline_label": assessment.deadline.strftime("Due %b %d · %I:%M %p") if assessment.deadline else "Open until your teacher closes it",
            "difficulty_name": difficulty_label(assessment.difficulty) if assessment.difficulty else None,
        },
        "can_start": taken < allowed and assessment.status == "published",
        "taken": taken,
        "allowed": allowed,
        "review_href": review_href,
        "has_summary": bool(material and material.status == "approved" and material.summary),
        "ask_teacher": ask_teacher_context(
            user, SUBJECTS[assessment.subject_slug]["name"], assessment.title
        ),
    }
    context.update(announcements_context(user))
    return render_template("assessment_lobby.html", **context)


@app.route("/assessments/<slug>/start", methods=["POST"])
def assessment_start(slug):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    assessment = Assessment.query.filter_by(slug=slug).first()
    if not assessment or assessment.status != "published":
        flash("That assessment is not available.", "danger")
        return redirect(url_for("home"))
    taken = Attempt.query.filter_by(user_id=user["id"], assessment_id=assessment.id, kind="assessment").count()
    allowed = assessment.attempt_limit + (1 if assessment.extra_attempt else 0)
    if taken >= allowed:
        flash("You have used your available attempts.", "danger")
        return redirect(url_for("assessment_lobby", slug=slug))
    if not assessment.questions:
        flash("This assessment has no questions yet.", "danger")
        return redirect(url_for("assessment_lobby", slug=slug))
    session["assessment_started"] = slug
    return redirect(url_for("assessment_take", slug=slug))


@app.route("/assessments/<slug>/take")
def assessment_take(slug):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    assessment = Assessment.query.filter_by(slug=slug).first()
    if not assessment or assessment.status != "published":
        flash("That assessment is not available.", "danger")
        return redirect(url_for("home"))
    taken = Attempt.query.filter_by(user_id=user["id"], assessment_id=assessment.id, kind="assessment").count()
    allowed = assessment.attempt_limit + (1 if assessment.extra_attempt else 0)
    if taken >= allowed:
        flash("You have used your available attempts.", "danger")
        return redirect(url_for("assessment_lobby", slug=slug))
    if session.get("assessment_started") != slug:
        flash("Start the assessment from the lobby first.", "danger")
        return redirect(url_for("assessment_lobby", slug=slug))
    questions = [q.as_dict() for q in assessment.questions]
    if not questions:
        flash("This assessment has no questions yet.", "danger")
        return redirect(url_for("assessment_lobby", slug=slug))
    attempt_label = "1 attempt" if allowed == 1 else f"Up to {allowed} attempts"
    context = {
        "user": user,
        "assessment": {
            "slug": assessment.slug,
            "subject_slug": assessment.subject_slug,
            "subject": SUBJECTS[assessment.subject_slug]["name"],
            "title": assessment.title,
            "difficulty_name": difficulty_label(assessment.difficulty) if assessment.difficulty else None,
            "attempt_label": attempt_label,
            "allowed_attempts": allowed,
        },
        "questions": questions,
    }
    context.update(announcements_context(user))
    return render_template("assessment_take.html", **context)


@app.route("/assessments/<slug>/submit", methods=["POST"])
def assessment_submit(slug):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    assessment = Assessment.query.filter_by(slug=slug).first()
    if not assessment or assessment.status == "draft":
        flash("Please start the assessment first.", "danger")
        return redirect(url_for("home"))
    taken = Attempt.query.filter_by(user_id=user["id"], assessment_id=assessment.id, kind="assessment").count()
    allowed = assessment.attempt_limit + (1 if assessment.extra_attempt else 0)
    started = session.get("assessment_started") == slug
    if taken >= allowed:
        flash("You have used your available attempts.", "danger")
        return redirect(url_for("assessment_lobby", slug=slug))
    if assessment.status == "closed" and not started:
        flash("This assessment is closed.", "danger")
        return redirect(url_for("assessment_lobby", slug=slug))
    questions = [q.as_dict() for q in assessment.questions]
    review_items, earned, auto_total, encouragement = score_answers(questions, request.form)
    attempt = Attempt(
        user_id=user["id"],
        assessment_id=assessment.id,
        kind="assessment",
        subject_slug=assessment.subject_slug,
        title=assessment.title,
        attempt_no=taken + 1,
        score_auto=earned,
        score_total_auto=auto_total,
        review_json=json.dumps(review_items),
        encouragement=encouragement,
        difficulty=assessment.difficulty,
    )
    db.session.add(attempt)
    db.session.commit()
    session.pop("assessment_started", None)
    if not assessment.release_scores:
        flash("Submitted. Scores will appear when your teacher releases them.", "success")
    return redirect(url_for("attempt_review", attempt_id=attempt.id))


@app.route("/practice")
def practice():
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] != "student":
        return redirect(url_for("home"))
    ready = []
    locked = []
    for material in Material.query.filter_by(status="approved").order_by(Material.created_at.desc()):
        ready.append(
            {
                "subject": SUBJECTS[material.subject_slug]["name"],
                "subject_slug": material.subject_slug,
                "title": f"{material.title} Practice Check",
                # Estimate only — question count is chosen later on Practice setup.
                "meta": "Approved material · ~10 min · Self-paced",
                "unlock_reason": None,
                "unlock_date": None,
                "href": url_for("practice_setup", subject_slug=material.subject_slug, material_slug=material.slug),
                "locked": False,
            }
        )
    for material in Material.query.filter_by(owner_id=user["id"], source="student", status="pending"):
        locked.append(
            {
                "subject": SUBJECTS[material.subject_slug]["name"],
                "subject_slug": material.subject_slug,
                "title": f"{material.title} practice",
                "meta": "Unlocks after teacher approval",
                "unlock_reason": "Unlocks after teacher approval",
                # No unlock_date in the Material model yet.
                "unlock_date": None,
                "href": None,
                "locked": True,
            }
        )
    practice_items = ready + locked
    subject_filters = [
        {"slug": meta["slug"], "name": meta["name"]}
        for meta in SUBJECTS.values()
        if any(item["subject_slug"] == meta["slug"] for item in practice_items)
    ]
    context = {
        "user": user,
        "practice_ready": ready,
        "practice_locked": locked,
        "practice_items": practice_items,
        "practice_subjects": subject_filters,
        "practice_available_count": len(ready),
    }
    context.update(announcements_context(user))
    return render_template("practice_hub.html", **context)


@app.route("/results")
def results():
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] != "student":
        return redirect(url_for("home"))
    filter_name = request.args.get("filter", "all")
    query = Attempt.query.filter_by(user_id=user["id"]).order_by(Attempt.submitted_at.desc())
    if filter_name == "assessments":
        query = query.filter_by(kind="assessment")
    elif filter_name == "practice":
        query = query.filter_by(kind="practice")
    else:
        filter_name = "all"
    items = []
    today = datetime.utcnow().date()
    for attempt in query.all():
        score_pending = bool(
            attempt.kind == "assessment"
            and attempt.assessment
            and not attempt.assessment.release_scores
        )
        score_percent = None if score_pending else attempt_score_percent(attempt)
        trend = None
        if attempt.kind == "practice":
            if score_pending:
                score_label = "Score pending"
                score_tone = "pending"
            elif attempt.score_total_auto:
                score_label = f"{attempt.score_auto} of {attempt.score_total_auto} reviewed"
                score_tone = "practice"
            else:
                score_label = "Reviewed"
                score_tone = "practice"
        elif score_pending:
            score_label = "Score pending"
            score_tone = "pending"
        elif attempt.score_total_auto:
            score_label = f"{attempt.score_auto}/{attempt.score_total_auto} correct"
            score_tone = assessment_score_tone(score_percent)
            if attempt.assessment_id and attempt.submitted_at:
                prior = (
                    Attempt.query.filter(
                        Attempt.user_id == user["id"],
                        Attempt.kind == "assessment",
                        Attempt.assessment_id == attempt.assessment_id,
                        Attempt.id != attempt.id,
                        Attempt.submitted_at.isnot(None),
                        Attempt.submitted_at < attempt.submitted_at,
                    )
                    .order_by(Attempt.submitted_at.desc())
                    .first()
                )
                if prior and prior.assessment and prior.assessment.release_scores:
                    trend = format_trend(score_percent, attempt_score_percent(prior))
        else:
            score_label = "Open response"
            score_tone = "neutral"
            score_percent = None
        attempts_exhausted = False
        if attempt.kind == "assessment" and attempt.assessment:
            taken, allowed = assessment_attempt_counts(user["id"], attempt.assessment)
            attempts_exhausted = taken >= allowed
        submitted_day = attempt.submitted_at.date() if attempt.submitted_at else None
        if submitted_day == today:
            history_bucket = "today"
        elif submitted_day and 0 < (today - submitted_day).days <= 6:
            history_bucket = "this-week"
        else:
            history_bucket = "earlier"
        items.append(
            {
                "kind": attempt.kind.title(),
                "kind_slug": attempt.kind,
                "subject": SUBJECTS.get(attempt.subject_slug, {}).get("name", ""),
                "subject_slug": attempt.subject_slug,
                "title": attempt.title,
                "meta": attempt_meta(attempt),
                "date_label": attempt.submitted_at.strftime("%b %d, %Y") if attempt.submitted_at else "Recent",
                "history_bucket": history_bucket,
                "score_label": score_label,
                "score_percent": score_percent,
                "score_tone": score_tone,
                "trend": trend,
                "difficulty": difficulty_label(attempt.difficulty) if attempt.difficulty else None,
                "action": "Review",
                "href": url_for("attempt_review", attempt_id=attempt.id),
                "attempts_exhausted": attempts_exhausted,
            }
        )
    result_groups = []
    if len(items) > 5:
        for key, label in (("today", "Today"), ("this-week", "This week"), ("earlier", "Earlier")):
            group_items = [item for item in items if item["history_bucket"] == key]
            if group_items:
                result_groups.append({"key": key, "label": label, "entries": group_items})
    story = None
    if items:
        latest = items[0]
        if latest.get("score_tone") == "pending":
            story = {
                "eyebrow": "Latest result",
                "title": latest["title"],
                "message": "Submitted and waiting for your teacher to release scores and feedback.",
                "cta_href": latest["href"],
                "cta_label": "Open submission",
            }
        elif latest.get("attempts_exhausted"):
            story = {
                "eyebrow": "Assessment closed",
                "title": latest["title"],
                "message": (
                    f"You’ve used your available attempts on this HOTS check. "
                    f"Review feedback in {latest['subject']}, practice the topic on your own, "
                    "or ask your teacher for an extra attempt."
                ),
                "cta_href": latest["href"],
                "cta_label": "Review feedback",
            }
        elif latest.get("score_percent") is not None and latest["score_percent"] < 70:
            story = {
                "eyebrow": "Focus next",
                "title": latest["title"],
                "message": f"Review the feedback in {latest['subject']}, then try another practice while it’s fresh.",
                "cta_href": latest["href"],
                "cta_label": "Review and improve",
            }
        else:
            story = {
                "eyebrow": "Keep building",
                "title": latest["title"],
                "message": "Revisit explanations, then continue with another practice or assessment.",
                "cta_href": latest["href"],
                "cta_label": "Review feedback",
            }
    context = {
        "user": user,
        "filter": filter_name,
        "result_items": items,
        "result_groups": result_groups,
        "results_story": story,
    }
    context.update(announcements_context(user))
    return render_template("results.html", **context)


@app.route("/profile", methods=["GET", "POST"])
def profile():
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    record = db.session.get(User, user["id"])
    if request.method == "POST":
        action = request.form.get("action", "photo")
        # Password changes live on /profile/password — keep old posts from breaking.
        if action == "password" or (
            request.form.get("current_password")
            and not request.files.get("photo")
            and action not in {"photo", "remove_photo"}
        ):
            return redirect(url_for("profile_password"))
        if action == "remove_photo":
            remove_avatar(record)
            db.session.commit()
            flash("Profile photo removed.", "success")
            return redirect(url_for("profile"))
        if action == "photo" or request.files.get("photo"):
            photo = request.files.get("photo")
            try:
                if not photo or not photo.filename:
                    raise ExtractError("Choose a photo to upload.")
                save_avatar(record, photo)
                db.session.commit()
                flash("Profile photo updated.", "success")
            except ExtractError as exc:
                flash(str(exc), "danger")
            return redirect(url_for("profile"))
        flash("Nothing to update.", "danger")
        return redirect(url_for("profile"))

    profile_subjects = []
    recent_activity = []
    if user["role"] == "student":
        for slug, meta in SUBJECTS.items():
            percent, insight, has_progress = bloom_progress(user["id"], slug)
            profile_subjects.append(
                {
                    "slug": slug,
                    "name": meta["name"],
                    "progress_label": progress_display_label(percent, has_progress, insight if has_progress else ""),
                    "progress_percent": percent,
                    "has_progress": has_progress,
                    "href": url_for("subject_hub", slug=slug),
                }
            )
        for attempt in (
            Attempt.query.filter_by(user_id=user["id"]).order_by(Attempt.submitted_at.desc()).limit(3)
        ):
            recent_activity.append(
                {
                    "title": attempt.title,
                    "meta": attempt_meta(attempt),
                    "kind": attempt.kind,
                    "subject": SUBJECTS.get(attempt.subject_slug, {}).get("name", "Subject"),
                    "subject_slug": attempt.subject_slug,
                    "href": url_for("attempt_review", attempt_id=attempt.id),
                }
            )
    context = {
        "user": user,
        "topbar_sub": "Profile",
        "role_nav": teacher_nav() if user["role"] == "teacher" else (admin_nav() if user["role"] == "admin" else None),
        "active_nav": "profile",
        "profile_stats": [
            {"label": "Subjects", "value": len(SUBJECTS), "tone": "blue"},
            {
                "label": "Practice & checks",
                "value": Attempt.query.filter_by(user_id=user["id"]).count(),
                "tone": "green",
            },
            {
                "label": "Unread messages",
                "value": unread_message_count(user["id"]),
                "tone": "violet",
            },
        ] if user["role"] == "student" else [],
        "profile_subjects": profile_subjects if user["role"] == "student" else [],
        "recent_activity": recent_activity if user["role"] == "student" else [],
    }
    context.update(announcements_context(user))
    return render_template("profile.html", **context)


@app.route("/profile/password", methods=["GET", "POST"])
def profile_password():
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    record = db.session.get(User, user["id"])
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not check_password_hash(record.password_hash, current):
            flash("Current password is incorrect.", "danger")
        elif len(new) < 8:
            flash("New password must be at least 8 characters.", "danger")
        elif new != confirm:
            flash("New passwords do not match.", "danger")
        else:
            record.password_hash = generate_password_hash(new)
            db.session.commit()
            flash("Password updated. Use your new password next time.", "success")
            return redirect(url_for("profile"))
        return redirect(url_for("profile_password"))

    context = {
        "user": user,
        "topbar_sub": "Change password",
        "role_nav": teacher_nav() if user["role"] == "teacher" else (admin_nav() if user["role"] == "admin" else None),
        "active_nav": "profile",
    }
    context.update(announcements_context(user))
    return render_template("profile_password.html", **context)


@app.route("/users/<int:user_id>/photo")
def user_photo(user_id):
    viewer = require_user()
    if not viewer:
        return redirect(url_for("login"))
    person = db.session.get(User, user_id)
    if not person or not person.avatar_filename:
        abort(404)
    path = avatar_file_path(person.avatar_filename)
    if not path:
        abort(404)
    return send_from_directory(app.config["AVATAR_FOLDER"], os.path.basename(person.avatar_filename))


@app.route("/announcements")
@app.route("/announcements/<int:announcement_id>")
def announcements(announcement_id=None):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] != "student":
        return redirect(url_for("home"))
    filter_name = request.args.get("filter", "all")
    if filter_name not in {"all", "unread", "English", "Math", "Science"}:
        filter_name = "all"
    q = (request.args.get("q") or "").strip()
    selected = None
    arrive = False
    if announcement_id:
        record = db.session.get(Announcement, announcement_id)
        if not record:
            if wants_json_response():
                return jsonify({"ok": False, "error": "That announcement is not available."}), 404
            flash("That announcement is not available.", "danger")
            return redirect(announcements_url(filter_name=filter_name, q=q))
        # Opening an announcement no longer marks it read on GET (prefetch-safe).
        # Marking happens via POST /announcements/<id>/read from the page/JS.
        session["announce_selected_id"] = announcement_id
        arrive = request.args.get("arrive") == "1"
    read_ids = announcement_read_ids(user["id"])
    selected_id = announcement_id
    records = Announcement.query.order_by(Announcement.created_at.desc()).all()
    notes = []
    for note in records:
        visible = note_matches_filter(note, filter_name, read_ids) and note_matches_search(note, q.lower())
        item = serialize_announcement(note, read_ids, selected_id, filter_name, q)
        if visible or item["selected"]:
            notes.append(item)
        if item["selected"]:
            selected = item
    if selected_id and not selected:
        if wants_json_response():
            return jsonify({"ok": False, "error": "That announcement is not available."}), 404
        flash("That announcement is not available.", "danger")
        return redirect(url_for("announcements"))
    unread_count = unread_announcement_count(user["id"])
    list_href = announcements_url(filter_name=filter_name, q=q, view="list")
    if wants_json_response() and selected:
        payload = jsonify(
            {
                "ok": True,
                "unread_announcements": unread_count,
                "selected": selected_announcement_payload(selected),
                "list_href": list_href,
            }
        )
        payload.headers["Cache-Control"] = "no-store"
        return payload
    restore_id = None
    if not announcement_id and request.args.get("view") != "list":
        restore_id = session.get("announce_selected_id")
        # Auto-open the first unread (or newest) so the detail pane is never a blank wall.
        if not selected and notes:
            pick = next((note for note in notes if note.get("unread")), notes[0])
            if not restore_id or not any(note["id"] == restore_id for note in notes):
                for note in notes:
                    note["selected"] = note["id"] == pick["id"]
                selected = pick
                session["announce_selected_id"] = pick["id"]
                restore_id = pick["id"]
            else:
                for note in notes:
                    note["selected"] = note["id"] == restore_id
                selected = next((note for note in notes if note["selected"]), None)
    subjects = sorted({note.subject for note in records if note.subject})
    context = {
        "user": user,
        "filter": filter_name,
        "q": q,
        "announcements": notes,
        "groups": group_announcements(notes),
        "selected": selected,
        "arrive": arrive,
        "has_announcements": bool(records),
        "unread_count": unread_count,
        "restore_id": restore_id,
        "show_subject_filters": len(subjects) > 1,
        "subject_chips": [
            {"name": subject, "href": announcements_url(filter_name=subject, q=q)} for subject in subjects
        ],
        "chip_all": announcements_url(q=q),
        "chip_unread": announcements_url(filter_name="unread", q=q),
        "list_href": list_href,
        "search_action": url_for("announcements"),
        "mark_all_url": url_for("announcement_mark_all_read"),
    }
    context.update(announcements_context(user))
    return render_template("announcements.html", **context)


@app.route("/announcements/read-all", methods=["POST"])
def announcement_mark_all_read():
    user = require_user()
    if not user:
        if wants_json_response():
            return jsonify({"ok": False, "error": "Please sign in to continue."}), 401
        return redirect(url_for("login"))
    if user["role"] != "student":
        if wants_json_response():
            return jsonify({"ok": False, "error": "You do not have access to that page."}), 403
        return redirect(url_for("home"))
    mark_all_announcements_read(user["id"])
    filter_name = request.form.get("filter") or request.args.get("filter") or "all"
    if filter_name not in {"all", "unread", "English", "Math", "Science"}:
        filter_name = "all"
    q = (request.form.get("q") or request.args.get("q") or "").strip()
    selected_id = request.form.get("selected_id", type=int) or session.get("announce_selected_id")
    if selected_id and not db.session.get(Announcement, selected_id):
        selected_id = None
    if filter_name == "unread":
        filter_name = "all"
    target = announcements_url(selected_id, filter_name, q)
    if wants_json_response():
        return jsonify(
            {
                "ok": True,
                "unread_announcements": unread_announcement_count(user["id"]),
                "selected_id": selected_id,
                "reload": request.form.get("filter") == "unread",
                "redirect": target,
            }
        )
    return redirect(target)


@app.route("/announcements/<int:announcement_id>/read", methods=["POST"])
def announcement_mark_read(announcement_id):
    user = require_user()
    if not user:
        if wants_json_response():
            return jsonify({"ok": False, "error": "Please sign in to continue."}), 401
        return redirect(url_for("login"))
    if user["role"] != "student":
        if wants_json_response():
            return jsonify({"ok": False, "error": "You do not have access to that page."}), 403
        return redirect(url_for("home"))
    if not mark_announcement_read(user["id"], announcement_id):
        if wants_json_response():
            return jsonify({"ok": False, "error": "Unable to update notification status. Please try again."}), 400
        flash("Unable to update notification status. Please try again.", "danger")
        return redirect(url_for("announcements"))
    session["announce_selected_id"] = announcement_id
    if wants_json_response():
        return jsonify(
            {
                "ok": True,
                "announcement_id": announcement_id,
                "unread_announcements": unread_announcement_count(user["id"]),
            }
        )
    return redirect(url_for("announcements", announcement_id=announcement_id))


@app.route("/teacher")
@require_role("teacher")
def teacher_home(user):
    slug = teacher_subject_slug(user)
    subject_name = SUBJECTS[slug]["name"]
    pending = Material.query.filter_by(subject_slug=slug, status="pending").count()
    approved = Material.query.filter_by(subject_slug=slug, status="approved").count()
    drafts = Assessment.query.filter_by(subject_slug=slug, status="draft").count()
    published = Assessment.query.filter_by(subject_slug=slug, status="published").count()
    unread = unread_message_count(user["id"])

    attention = []
    if unread:
        attention.append(
            {
                "type": "messages",
                "priority": "primary",
                "subject": subject_name,
                "subject_slug": slug,
                "kicker": "Messages",
                "title": f"{unread} unread message{'s' if unread != 1 else ''}",
                "meta": "Private academic chat with your section",
                "action": "Reply",
                "href": url_for("messages_inbox"),
            }
        )
    pending_materials = Material.query.filter_by(subject_slug=slug, status="pending").order_by(Material.created_at.desc()).all()
    if pending_materials:
        attention.append(
            {
                "type": "upload",
                "priority": "primary" if not attention else "secondary",
                "subject": subject_name,
                "subject_slug": slug,
                "kicker": "Materials",
                "title": f"{pending} material{'s' if pending != 1 else ''} pending review",
                "meta": "Check the file and summary before students can practice",
                "action": "Review",
                "href": (
                    url_for("teacher_material_review", material_id=pending_materials[0].id)
                    if pending == 1
                    else url_for("teacher_materials")
                ),
            }
        )
    draft_sets = Assessment.query.filter_by(subject_slug=slug, status="draft").order_by(Assessment.created_at.desc()).all()
    if draft_sets:
        attention.append(
            {
                "type": "assessment",
                "priority": "primary" if not attention else "secondary",
                "subject": subject_name,
                "subject_slug": slug,
                "kicker": "HOTS",
                "title": f"{drafts} draft HOTS set{'s' if drafts != 1 else ''}",
                "meta": "Edit, regenerate, then publish to your section",
                "action": "Publish",
                "href": url_for("teacher_hots"),
            }
        )
    awaiting_release = assessments_awaiting_release(slug)
    if awaiting_release:
        n = len(awaiting_release)
        attention.append(
            {
                "type": "release",
                "priority": "primary" if not attention else "secondary",
                "subject": subject_name,
                "subject_slug": slug,
                "kicker": "Monitor",
                "title": f"{n} assessment{'s' if n != 1 else ''} awaiting release",
                "meta": "Students have submitted — release scores, answers, or feedback when ready",
                "action": "Open Monitor",
                "href": url_for("teacher_monitor"),
            }
        )

    # Class average from auto-scored assessment attempts in this subject (honest; no fake %).
    score_attempts = Attempt.query.filter_by(subject_slug=slug, kind="assessment").all()
    percents = [
        int(100 * item.score_auto / item.score_total_auto)
        for item in score_attempts
        if item.score_total_auto
    ]
    class_pulse = {
        "value": f"{int(round(sum(percents) / len(percents)))}%" if percents else "—",
        "label": "Class avg score" if percents else "No scores yet",
        "has_data": bool(percents),
        "href": url_for("teacher_monitor"),
    }

    first_name = (user.get("name") or "Teacher").split(" ")[0]
    return render_template(
        "teacher_home.html",
        user=user,
        topbar_sub=f"Teacher · {subject_name}",
        role_nav=teacher_nav(),
        active_nav="home",
        subject_name=subject_name,
        subject_slug=slug,
        greeting=f"Hi, {first_name}",
        guide_note=f"Here’s what needs your attention across {subject_name} today.",
        class_pulse=class_pulse,
        stats=[
            {
                "label": "Approved materials",
                "value": str(approved),
                "meta": "Ready for class",
                "tone": "blue",
                "href": url_for("teacher_materials"),
            },
            {
                "label": "Draft HOTS sets",
                "value": str(drafts),
                "meta": "Needs review",
                "tone": "amber",
                "href": url_for("teacher_hots"),
            },
            {
                "label": "Pending review",
                "value": str(pending),
                "meta": "File + summary",
                "tone": "gray",
                "href": url_for("teacher_materials"),
            },
            {
                "label": "Published assessments",
                "value": str(published),
                "meta": "Visible to section",
                "tone": "green",
                "href": url_for("teacher_monitor"),
            },
        ],
        attention=attention,
        # Use "note" not "copy" — Jinja {{ empty_cta.copy }} resolves to dict.copy.
        empty_cta={
            "title": "Nothing pending right now.",
            "note": "No drafts, uploads, or unread messages need you right now.",
            "action": "Upload a new lesson",
            "href": url_for("teacher_materials"),
        },
    )


def material_review_payload(material: Material) -> dict:
    owner = material.owner
    has_file = bool(material_file_path(material))
    return {
        "id": material.id,
        "title": material.title,
        "status": material.status,
        "source": material.source,
        "source_label": "Student backup" if material.source == "student" else "Teacher upload",
        "owner_name": owner.name if owner else "Unknown",
        "filename": stored_filename_label(material.filename),
        "char_count": len(material.extracted_text or ""),
        "extracted_text": material.extracted_text or "",
        "reject_reason": material.reject_reason,
        "created_at": material.created_at.strftime("%b %d, %Y") if material.created_at else "",
        "has_file": has_file,
        "file_href": url_for("teacher_material_file", material_id=material.id) if has_file else None,
        "review_href": url_for("teacher_material_review", material_id=material.id),
        "has_summary": bool(material.summary),
        "summary": {
            "intro": material.summary.intro if material.summary else "",
            "sections": material.summary.sections() if material.summary else [],
        },
        "student_summary_href": (
            url_for("summary_reader", slug=material.subject_slug, material_slug=material.slug)
            if material.status == "approved" and material.summary
            else None
        ),
    }


@app.route("/teacher/materials", methods=["GET", "POST"])
@require_role("teacher")
def teacher_materials(user):
    slug = teacher_subject_slug(user)
    if request.method == "POST":
        action = request.form.get("action", "upload")
        if action in {"approve", "reject"}:
            material = teacher_owned_material(user, request.form.get("material_id", type=int))
            if not material:
                flash("That material is not available.", "danger")
                return redirect(url_for("teacher_materials"))
            if action == "reject":
                reject_material(material)
                db.session.commit()
                flash("Upload rejected.", "success")
                return redirect(url_for("teacher_materials"))
            try:
                deploy_material(material)
                db.session.commit()
                flash(f"{material.title} is now available to students.", "success")
            except Exception:
                flash("Could not generate a summary. Open the review page and try again.", "danger")
            return redirect(url_for("teacher_materials"))
        title = request.form.get("title", "").strip()
        notes = request.form.get("notes", "").strip()
        file = request.files.get("file")
        try:
            if file and file.filename:
                filename, data = save_file(file)
            elif notes:
                filename, data = "pasted-lesson.txt", notes.encode("utf-8")
            else:
                raise ExtractError("Upload a file or paste lesson text.")
            material = create_material(title or path_stem(filename), slug, user["id"], "teacher", filename, data)
            flash("Material uploaded. Review the summary before deploying it to students.", "success")
            return redirect(url_for("teacher_material_review", material_id=material.id))
        except ExtractError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("teacher_materials"))

    items = [material_review_payload(item) for item in Material.query.filter_by(subject_slug=slug).order_by(Material.created_at.desc())]
    pending = [item for item in items if item["status"] == "pending"]
    deployed = [item for item in items if item["status"] == "approved"]
    rejected = [item for item in items if item["status"] == "rejected"]
    return render_template(
        "teacher_materials.html",
        user=user,
        topbar_sub=f"Teacher · {SUBJECTS[slug]['name']}",
        role_nav=teacher_nav(),
        active_nav="materials",
        subject_name=SUBJECTS[slug]["name"],
        subject_slug=slug,
        pending=pending,
        deployed=deployed,
        rejected=rejected,
    )


@app.route("/teacher/materials/<int:material_id>", methods=["GET", "POST"])
@require_role("teacher")
def teacher_material_review(user, material_id):
    material = teacher_owned_material(user, material_id)
    if not material:
        flash("That material is not available.", "danger")
        return redirect(url_for("teacher_materials"))
    if request.method == "POST":
        action = request.form.get("action")
        if action == "summarize":
            try:
                attach_summary(material)
                db.session.commit()
                flash("Summary updated. Review it before deploying.", "success")
            except Exception:
                flash("Could not generate a summary. Try again or paste more lesson text.", "danger")
            return redirect(url_for("teacher_material_review", material_id=material.id))
        if action == "approve":
            try:
                deploy_material(material)
                db.session.commit()
                flash(f"{material.title} is now available to students.", "success")
                return redirect(url_for("teacher_materials"))
            except Exception:
                flash("Could not deploy this material. Generate a summary first.", "danger")
            return redirect(url_for("teacher_material_review", material_id=material.id))
        if action == "reject":
            reject_material(material)
            db.session.commit()
            flash("Upload rejected.", "success")
            return redirect(url_for("teacher_materials"))
        return redirect(url_for("teacher_material_review", material_id=material.id))

    slug = teacher_subject_slug(user)
    return render_template(
        "teacher_material_review.html",
        user=user,
        topbar_sub=f"Teacher · {SUBJECTS[slug]['name']}",
        role_nav=teacher_nav(),
        active_nav="materials",
        subject_name=SUBJECTS[slug]["name"],
        material=material_review_payload(material),
    )


@app.route("/teacher/materials/<int:material_id>/file")
@require_role("teacher")
def teacher_material_file(user, material_id):
    material = teacher_owned_material(user, material_id)
    if not material:
        abort(404)
    path = material_file_path(material)
    if not path:
        flash("That uploaded file is not stored on this server.", "danger")
        return redirect(url_for("teacher_material_review", material_id=material.id))
    download_name = stored_filename_label(material.filename)
    inline = os.path.splitext(download_name)[1].lower() in {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        os.path.basename(material.filename),
        as_attachment=not inline,
        download_name=download_name,
    )


@app.route("/teacher/hots", methods=["GET", "POST"])
@require_role("teacher")
def teacher_hots(user):
    slug = teacher_subject_slug(user)
    if request.method == "POST":
        action = request.form.get("action", "generate")
        if action == "generate":
            material = Material.query.filter_by(id=request.form.get("material_id", type=int), subject_slug=slug, status="approved").first()
            if not material:
                flash("Choose an approved material first.", "danger")
                return redirect(url_for("teacher_hots"))
            try:
                count = max(1, min(int(request.form.get("count") or 5), 8))
            except ValueError:
                count = 5
            bloom = request.form.get("bloom") or "mixed"
            difficulty = normalize_difficulty(request.form.get("difficulty"))
            questions = generate_hots_questions(
                material.title,
                material.extracted_text,
                SUBJECTS[slug]["name"],
                bloom,
                count,
                ["mcq", "essay", "problem"],
                difficulty,
            )
            assessment = Assessment(
                slug=unique_slug(f"{material.title}-hots", Assessment),
                title=f"{material.title} HOTS Assessment",
                subject_slug=slug,
                material_id=material.id,
                created_by=user["id"],
                status="draft",
                difficulty=difficulty,
            )
            db.session.add(assessment)
            db.session.flush()
            for item in questions:
                db.session.add(
                    Question(
                        assessment_id=assessment.id,
                        bloom=item["bloom"],
                        qtype=item["type"],
                        prompt=item["prompt"],
                        options_json=json.dumps(item.get("options") or []),
                        answer=item.get("answer"),
                        explanation=item.get("explanation") or "",
                        rubric=item.get("rubric"),
                        citation=item.get("citation") or "",
                    )
                )
            db.session.commit()
            flash("HOTS set generated. Review items before publishing.", "success")
        elif action == "publish":
            assessment = Assessment.query.filter_by(id=request.form.get("assessment_id", type=int), subject_slug=slug).first()
            if assessment:
                assessment.status = "published"
                deadline = request.form.get("deadline")
                if deadline:
                    try:
                        assessment.deadline = datetime.fromisoformat(deadline)
                    except ValueError:
                        assessment.deadline = datetime.utcnow() + timedelta(days=2)
                else:
                    assessment.deadline = datetime.utcnow() + timedelta(days=2)
                db.session.commit()
                flash("Assessment published to the section.", "success")
        elif action == "regenerate":
            question = db.session.get(Question, request.form.get("question_id", type=int))
            if question and question.assessment.subject_slug == slug:
                material = question.assessment.material
                generated = generate_hots_questions(
                    material.title if material else question.assessment.title,
                    material.extracted_text if material else question.prompt,
                    SUBJECTS[slug]["name"],
                    question.bloom,
                    1,
                    [question.qtype],
                    question.assessment.difficulty or "medium",
                )
                if not generated:
                    flash("Could not regenerate that question.", "danger")
                    return redirect(url_for("teacher_hots"))
                item = generated[0]
                question.prompt = item["prompt"]
                question.options_json = json.dumps(item.get("options") or [])
                question.answer = item.get("answer")
                question.explanation = item.get("explanation") or ""
                question.rubric = item.get("rubric")
                question.citation = item.get("citation") or ""
                db.session.commit()
                flash("Question regenerated.", "success")
        return redirect(url_for("teacher_hots"))

    materials = Material.query.filter_by(subject_slug=slug, status="approved").all()
    assessments = Assessment.query.filter_by(subject_slug=slug).order_by(Assessment.created_at.desc()).all()
    return render_template(
        "teacher_hots.html",
        user=user,
        topbar_sub=f"Teacher · {SUBJECTS[slug]['name']}",
        role_nav=teacher_nav(),
        active_nav="hots",
        materials=materials,
        assessments=assessments,
        subject_name=SUBJECTS[slug]["name"],
        subject_slug=slug,
    )


@app.route("/teacher/monitor", methods=["GET", "POST"])
@require_role("teacher")
def teacher_monitor(user):
    slug = teacher_subject_slug(user)
    if request.method == "POST":
        assessment = Assessment.query.filter_by(id=request.form.get("assessment_id", type=int), subject_slug=slug).first()
        action = request.form.get("action")
        if assessment and action == "close":
            assessment.status = "closed"
            db.session.commit()
            flash("Assessment closed. Students already answering may still submit.", "success")
        elif assessment and action == "reopen":
            assessment.status = "published"
            assessment.extra_attempt = True
            db.session.commit()
            flash("Assessment reopened with one extra attempt. Original attempts stay in history.", "success")
        elif assessment and action == "release_scores":
            assessment.release_scores = True
            db.session.commit()
            flash("Scores released.", "success")
        elif assessment and action == "release_answers":
            assessment.release_answers = True
            db.session.commit()
            flash("Answers released.", "success")
        elif assessment and action == "release_feedback":
            assessment.release_feedback = True
            db.session.commit()
            flash("Feedback released.", "success")
        return redirect(url_for("teacher_monitor"))

    student_rows = teacher_student_progress(user, slug)
    student_count = len(student_rows)
    scored = [row["percent"] for row in student_rows if row["percent"] is not None]
    class_avg = int(round(sum(scored) / len(scored))) if scored else None
    submitted_students = sum(1 for row in student_rows if row["assessment_n"])
    panels = []
    for assessment in Assessment.query.filter_by(subject_slug=slug).order_by(Assessment.created_at.desc()):
        attempts = (
            Attempt.query.filter_by(assessment_id=assessment.id, kind="assessment")
            .order_by(Attempt.submitted_at.desc())
            .all()
        )
        percents = [attempt_score_percent(item) for item in attempts if item.score_total_auto]
        avg = int(round(sum(percents) / len(percents))) if percents else None
        panels.append(
            {
                "title": assessment.title,
                "assessment_id": assessment.id,
                "status": assessment.status,
                "status_label": assessment.status.title(),
                "submitted": len(attempts),
                "student_count": student_count or 1,
                "avg": avg,
                "difficulty": difficulty_label(assessment.difficulty) if assessment.difficulty else "Medium",
                "extra_attempt": assessment.extra_attempt,
                "release_scores": assessment.release_scores,
                "release_answers": assessment.release_answers,
                "release_feedback": assessment.release_feedback,
                "releases": [
                    {"label": "Scores", "on": assessment.release_scores},
                    {"label": "Answers", "on": assessment.release_answers},
                    {"label": "Feedback", "on": assessment.release_feedback},
                ],
                "submissions": [
                    {
                        "name": item.user.name if item.user else "Student",
                        "meta": attempt_meta(item),
                        "href": url_for("attempt_review", attempt_id=item.id),
                        "percent": attempt_score_percent(item),
                        "tone": assessment_score_tone(attempt_score_percent(item)),
                    }
                    for item in attempts
                ],
            }
        )
    practice_n = Attempt.query.filter_by(kind="practice", subject_slug=slug).count()
    return render_template(
        "teacher_monitor.html",
        user=user,
        topbar_sub=f"Teacher · {SUBJECTS[slug]['name']}",
        role_nav=teacher_nav(),
        active_nav="monitor",
        panels=panels,
        practice_n=practice_n,
        subject_name=SUBJECTS[slug]["name"],
        subject_slug=slug,
        students=student_rows,
        class_avg=class_avg,
        submitted_students=submitted_students,
    )


@app.route("/teacher/announce", methods=["GET", "POST"])
@require_role("teacher")
def teacher_announce(user):
    slug = teacher_subject_slug(user)
    label = SUBJECTS[slug]["announce"]
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = normalize_announcement_body(request.form.get("body", ""))
        if not title:
            flash("Please add a title.", "danger")
        else:
            db.session.add(Announcement(subject=label, title=title, body=body, teacher_id=user["id"]))
            db.session.commit()
            flash("Announcement posted to your subject feed.", "success")
        return redirect(url_for("teacher_announce"))
    notes = Announcement.query.filter_by(subject=label).order_by(Announcement.created_at.desc()).all()
    panels = [
        {
            "kicker": note.subject,
            "title": note.title,
            "meta": note.created_at.strftime("%b %d") + (f" — {note.body}" if note.body else ""),
            "action": None,
            "action_href": None,
            "soft": True,
        }
        for note in notes
    ]
    return render_template(
        "staff_page.html",
        user=user,
        topbar_sub="Announcements",
        role_nav=teacher_nav(),
        active_nav="announce",
        title="Subject announcements",
        subtitle="Posts appear in the shared student feed, filterable by subject.",
        panels=panels,
        form_blocks=[
            {
                "title": "New announcement",
                "note": "Keep it short and student-friendly.",
                "action": url_for("teacher_announce"),
                "submit": "Post announcement",
                "loading": "Posting announcement…",
                "fields": [
                    {"id": "title", "name": "title", "label": "Title", "type": "text", "placeholder": "Assessment reminder", "required": True},
                    {"id": "body", "name": "body", "label": "Message", "type": "textarea", "placeholder": "Write your announcement...", "required": True},
                ],
            }
        ],
    )


@app.route("/admin")
@require_role("admin")
def admin_home(user):
    monitor = build_admin_class_monitor()
    context = {
        "user": user,
        "topbar_sub": "Admin",
        "role_nav": admin_nav(),
        "active_nav": "home",
        "title": "Class monitor",
        "subtitle": "See whether the Grade 7 pilot section is progressing — participation, HOTS strength, and student-by-student status.",
        "monitor": monitor,
    }
    context.update(announcements_context(user))
    return render_template("admin_monitor.html", **context)


@app.route("/admin/users", methods=["GET", "POST"])
@require_role("admin")
def admin_users(user):
    if request.method == "POST":
        raw = request.form.get("csv", "").strip()
        created = 0
        reader = csv.reader(io.StringIO(raw))
        for row in reader:
            if not row or len(row) < 4:
                continue
            email, name, role, password = [part.strip() for part in row[:4]]
            subject = row[4].strip() if len(row) > 4 else None
            email = email.lower()
            role = role.lower()
            if role not in {"student", "teacher", "admin"} or User.query.filter_by(email=email).first():
                continue
            if role == "teacher" and subject in {"English", "Mathematics", "Science", "Math"}:
                subject = "Mathematics" if subject == "Math" else subject
            else:
                subject = subject if role == "teacher" else None
            db.session.add(
                User(
                    email=email,
                    name=name or email.split("@")[0],
                    role=role,
                    subject=subject,
                    password_hash=generate_password_hash(password or "Temp1234"),
                )
            )
            created += 1
        db.session.commit()
        if created:
            flash(f"Imported {created} user(s). They can sign in with their temporary passwords.", "success")
        else:
            flash("No new users imported. Check the CSV format, or those emails may already exist.", "danger")
        return redirect(url_for("admin_users"))

    panels = []
    for record in User.query.order_by(User.role, User.name).all():
        panels.append(
            {
                "kicker": record.role.title() + (f" · {record.subject}" if record.subject else ""),
                "title": record.name,
                "meta": record.email,
                "action": None,
                "action_href": None,
                "soft": True,
            }
        )
    return render_template(
        "staff_page.html",
        user=user,
        topbar_sub="Users",
        role_nav=admin_nav(),
        active_nav="users",
        title="Users",
        subtitle="Bulk import school emails, names, roles, and temporary passwords.",
        panels=panels,
        form_blocks=[
            {
                "title": "Bulk import",
                "note": "CSV rows: email, full name, role, temporary password, subject (teachers)",
                "action": url_for("admin_users"),
                "submit": "Import users",
                "loading": "Importing users…",
                "confirm": "Import these accounts? Temporary passwords will be set from the CSV.",
                "sample_target": "csv",
                "sample_value": "student2@letran-calamba.edu.ph, Ana Cruz, student, Temp1234",
                "fields": [
                    {
                        "id": "csv",
                        "name": "csv",
                        "label": "CSV data",
                        "type": "textarea",
                        "placeholder": "student2@letran-calamba.edu.ph, Ana Cruz, student, Temp1234",
                        "required": True,
                    }
                ],
            }
        ],
    )


@app.route("/admin/section")
@require_role("admin")
def admin_section(user):
    teachers = ", ".join(t.subject or t.name for t in User.query.filter_by(role="teacher").all()) or "None yet"
    return render_template(
        "staff_page.html",
        user=user,
        topbar_sub="Section",
        role_nav=admin_nav(),
        active_nav="section",
        title="Section management",
        subtitle="One Grade 7 pilot section with English, Math, and Science teachers.",
        panels=[
            {
                "kicker": "Pilot section",
                "title": "Grade 7 · Section A",
                "meta": f"{User.query.filter_by(role='student').count()} students · Teachers: {teachers}",
                "action": None,
                "action_href": None,
                "soft": True,
            }
        ],
        form_blocks=[],
    )


@app.route("/admin/reports")
@require_role("admin")
def admin_reports(user):
    monitor = build_admin_class_monitor()
    context = {
        "user": user,
        "topbar_sub": "Monitor",
        "role_nav": admin_nav(),
        "active_nav": "reports",
        "title": "Reports & analytics",
        "subtitle": "Class functioning at a glance — critical-thinking (HOTS) stats, subject averages, and who still needs support.",
        "monitor": monitor,
    }
    context.update(announcements_context(user))
    return render_template("admin_monitor.html", **context)


@app.route("/admin/settings", methods=["GET", "POST"])
@require_role("admin")
def admin_settings(user):
    if request.method == "POST":
        # No editable controls are exposed — avoid a fake "saved" success.
        flash("These are read-only pilot notes. Change upload/AI behavior via environment settings.", "danger")
        return redirect(url_for("admin_settings"))
    return render_template(
        "staff_page.html",
        user=user,
        topbar_sub="Settings",
        role_nav=admin_nav(),
        active_nav="settings",
        title="System settings",
        subtitle="Read-only pilot defaults. Upload limits and AI keys are configured on the server.",
        panels=[
            {
                "kicker": "Uploads",
                "title": "20 MB · 100 pages · reject weak scans",
                "meta": "Configured in app settings · No OCR in research scope",
                "action": None,
                "action_href": None,
                "soft": True,
            },
            {
                "kicker": "Privacy",
                "title": "Minimize student data in AI prompts",
                "meta": "Role-based access · school email accounts",
                "action": None,
                "action_href": None,
                "soft": True,
            },
            {
                "kicker": "AI",
                "title": "Prompt engineering only",
                "meta": "Set OPENAI_API_KEY or GEMINI_API_KEY. Without a key, Bloom uses a grounded fallback generator.",
                "action": None,
                "action_href": None,
                "soft": True,
            },
        ],
        form_blocks=[],
    )


@app.route("/messages")
def messages_inbox():
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] == "admin":
        flash("Messages are for students and teachers.", "danger")
        return redirect(url_for("home"))

    threads = []
    if user["role"] == "student":
        teachers = User.query.filter_by(role="teacher").order_by(User.subject, User.name).all()
        for teacher in teachers:
            if not same_section(user, teacher):
                continue
            conversation = Conversation.query.filter_by(student_id=user["id"], teacher_id=teacher.id).first()
            if conversation and conversation.messages:
                threads.append(conversation_preview(conversation, user["id"]))
            else:
                subject_slug = next(
                    (slug for slug, meta in SUBJECTS.items() if meta["name"] == (teacher.subject or "")),
                    "general",
                )
                preview = "No messages yet — start a private question about a lesson or assessment"
                threads.append(
                    {
                        "id": 0,
                        "other_id": teacher.id,
                        "name": teacher.name,
                        "meta": teacher.subject or "Teacher",
                        "subject_slug": subject_slug,
                        "initials": initials(teacher.name),
                        "photo_url": photo_url_for(teacher),
                        "preview": preview,
                        "when": "",
                        "unread": 0,
                        "started": False,
                        "href": url_for("messages_thread", user_id=teacher.id),
                        "search": f"{teacher.name} {teacher.subject or ''} {preview}".lower(),
                    }
                )
    else:
        conversations = (
            Conversation.query.filter_by(teacher_id=user["id"])
            .order_by(Conversation.updated_at.desc())
            .all()
        )
        threads = [
            conversation_preview(item, user["id"])
            for item in conversations
            if item.messages and item.student and same_section(user, item.student)
        ]
        threads.sort(key=lambda item: (0 if item["unread"] else 1, item["when"] == ""))

    subject_filters = [
        {"slug": meta["slug"], "name": meta["name"]}
        for meta in SUBJECTS.values()
        if any(thread.get("subject_slug") == meta["slug"] for thread in threads)
    ]
    context = {
        "user": user,
        "threads": threads,
        "message_subjects": subject_filters,
        "is_teacher": user["role"] == "teacher",
        "topbar_sub": "Messages",
        "role_nav": teacher_nav() if user["role"] == "teacher" else None,
        "active_nav": "messages",
    }
    context.update(announcements_context(user))
    return render_template("messages_inbox.html", **context)


@app.route("/messages/with/<int:user_id>", methods=["GET", "POST"])
def messages_thread(user_id):
    user = require_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] == "admin":
        flash("Messages are for students and teachers.", "danger")
        return redirect(url_for("home"))

    other = db.session.get(User, user_id)
    if not other or not allowed_chat_partner(user, other):
        flash(
            "You can only message your teachers."
            if user["role"] == "student"
            else "You can only message students in your section.",
            "danger",
        )
        return redirect(url_for("messages_inbox"))

    conversation = find_conversation(user, other)
    if user["role"] == "teacher" and (not conversation or not conversation.messages):
        flash("That student has not started a conversation yet.", "danger")
        return redirect(url_for("messages_inbox"))

    if request.method == "POST":
        body = (request.form.get("body") or "").strip()
        if not body:
            flash("Please type a message first.", "danger")
        elif len(body) > 2000:
            flash("Messages are limited to 2,000 characters.", "danger")
        else:
            if user["role"] == "student":
                conversation = get_or_create_conversation(user["id"], other.id)
            elif not conversation:
                flash("That student has not started a conversation yet.", "danger")
                if request.headers.get("X-Requested-With") == "fetch":
                    return jsonify({"ok": False, "error": "Could not send that message."}), 400
                return redirect(url_for("messages_inbox"))
            if conversation and can_access_conversation(user, conversation):
                db.session.add(
                    ChatMessage(conversation_id=conversation.id, sender_id=user["id"], body=body)
                )
                conversation.updated_at = datetime.utcnow()
                db.session.commit()
                if request.headers.get("X-Requested-With") == "fetch":
                    last = conversation.messages[-1]
                    return jsonify({"ok": True, "message": serialize_message(last, user["id"])})
            else:
                flash("You do not have access to that conversation.", "danger")
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": "Could not send that message."}), 400
        return redirect(url_for("messages_thread", user_id=other.id))

    # Mark-as-read is POST-only (see messages_mark_read + messages.js) so GET stays prefetch-safe.
    draft = (request.args.get("draft") or "").strip()[:2000]
    messages = [serialize_message(item, user["id"]) for item in (conversation.messages if conversation else [])]
    context = {
        "user": user,
        "other": {
            "id": other.id,
            "name": other.name,
            "meta": other.subject or other.role.title(),
            "subject_slug": subject_slug_from_name(other.subject),
            "initials": initials(other.name),
            "photo_url": photo_url_for(other),
        },
        "messages": messages,
        "draft": draft,
        "poll_url": url_for("messages_updates", user_id=other.id),
        "send_url": url_for("messages_thread", user_id=other.id),
        "topbar_sub": "Messages",
        "role_nav": teacher_nav() if user["role"] == "teacher" else None,
        "active_nav": "messages",
    }
    context.update(announcements_context(user))
    return render_template("messages_thread.html", **context)


@app.route("/messages/with/<int:user_id>/updates")
def messages_updates(user_id):
    user = require_user()
    if not user:
        return jsonify({"ok": False}), 401
    other = db.session.get(User, user_id)
    if not other or not allowed_chat_partner(user, other):
        return jsonify({"ok": False}), 403
    conversation = find_conversation(user, other)
    if not conversation:
        return jsonify({"ok": True, "messages": [], "read_ids": [], "unread_messages": unread_message_count(user["id"])})
    if not can_access_conversation(user, conversation):
        return jsonify({"ok": False}), 403
    # GET is read-only (prefetch-safe). Marking happens via POST /read (messages.js).
    after = request.args.get("after", type=int) or 0
    fresh = [item for item in conversation.messages if item.id > after]
    read_ids = [item.id for item in conversation.messages if item.sender_id == user["id"] and item.read_at]
    return jsonify(
        {
            "ok": True,
            "messages": [serialize_message(item, user["id"]) for item in fresh],
            "read_ids": read_ids,
            "unread_messages": unread_message_count(user["id"]),
        }
    )


@app.route("/messages/with/<int:user_id>/read", methods=["POST"])
def messages_mark_read(user_id):
    user = require_user()
    if not user:
        return jsonify({"ok": False}), 401
    other = db.session.get(User, user_id)
    if not other or not allowed_chat_partner(user, other):
        return jsonify({"ok": False}), 403
    conversation = find_conversation(user, other)
    if conversation and can_access_conversation(user, conversation):
        mark_conversation_read(conversation, user["id"])
    return jsonify({"ok": True, "unread_messages": unread_message_count(user["id"])})


@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="images/letran-calamba-logo.png"))


@app.errorhandler(403)
def forbidden(_error):
    return render_template(
        "error.html",
        user=current_user(),
        code=403,
        title="You don’t have access",
        message="That page is for a different role in Bloom. Go home and open a page you can use.",
    ), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template(
        "error.html",
        user=current_user(),
        code=404,
        title="Page not found",
        message="That page is not in Bloom. Head back home and try another path.",
    ), 404


@app.errorhandler(413)
def too_large(_error):
    flash("That file is too large. Uploads are limited to 20 MB.", "danger")
    return redirect(request.referrer or url_for("home"))


@app.errorhandler(500)
def server_error(_error):
    return render_template(
        "error.html",
        user=current_user(),
        code=500,
        title="Something went wrong",
        message="Bloom hit an unexpected error. Try again in a moment, or go home and continue from there.",
    ), 500


@app.route("/logout", methods=["GET", "POST"])
def logout():
    if request.method == "GET":
        # Prefetch-safe: show a confirm form instead of clearing the session on GET.
        user = current_user()
        return render_template("logout.html", user=user)
    session.clear()
    flash("You signed out of Bloom.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    on_railway = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"))
    debug = os.environ.get("FLASK_DEBUG", "0" if (IS_PRODUCTION or on_railway) else "1").lower() in {
        "1",
        "true",
        "yes",
    }
    host = "0.0.0.0" if (on_railway or IS_PRODUCTION) else "127.0.0.1"
    app.run(debug=debug, host=host, port=int(os.environ.get("PORT", "5001")))
