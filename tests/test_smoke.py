"""Smoke tests for Bloom auth, CSRF, and attempt ownership."""

import os
import tempfile
import unittest
from io import BytesIO

# Isolate a temp DB before importing the app module side effects.
os.environ["BLOOM_ENV"] = "development"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["BLOOM_SHOW_PILOTS"] = "0"
os.environ["FLASK_DEBUG"] = "0"

_tmp = tempfile.TemporaryDirectory()
os.environ["BLOOM_TEST_DB"] = os.path.join(_tmp.name, "test.db")

import app as bloom  # noqa: E402
from models import (  # noqa: E402
    Announcement,
    AnnouncementRead,
    AcademicTerm,
    Assessment,
    Attempt,
    Material,
    SchoolSection,
    SchoolYear,
    Question,
    Summary,
    User,
    db,
)
from werkzeug.security import generate_password_hash  # noqa: E402


class BloomSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bloom.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.environ["BLOOM_TEST_DB"]
        bloom.app.config["TESTING"] = True
        bloom.app.config["WTF_CSRF_ENABLED"] = False  # unused; custom CSRF still active
        bloom.app.config["AVATAR_FOLDER"] = os.path.join(_tmp.name, "avatars")
        os.makedirs(bloom.app.config["AVATAR_FOLDER"], exist_ok=True)
        with bloom.app.app_context():
            db.drop_all()
            db.create_all()
            bloom.seed_default_courses()
            bloom.seed_default_terms()
            student = User(
                email="student@test.local",
                name="Test Student",
                role="student",
                password_hash=generate_password_hash("student123"),
            )
            other = User(
                email="other@test.local",
                name="Other Student",
                role="student",
                password_hash=generate_password_hash("student123"),
            )
            teacher = User(
                email="teacher@test.local",
                name="Test Teacher",
                role="teacher",
                subject="Science",
                password_hash=generate_password_hash("teacher123"),
            )
            admin = User(
                email="admin@test.local",
                name="Test Admin",
                role="admin",
                password_hash=generate_password_hash("admin123"),
            )
            db.session.add_all([student, other, teacher, admin])
            db.session.commit()
            material = Material(
                slug="ecosystems",
                title="Ecosystems",
                subject_slug="science",
                owner_id=teacher.id,
                source="teacher",
                status="approved",
                filename="ecosystems.txt",
                extracted_text="Energy moves through food chains in an ecosystem.",
            )
            db.session.add(material)
            db.session.flush()
            db.session.add(
                Summary(
                    material_id=material.id,
                    intro="A short guide to ecosystems.",
                    sections_json='[{"id": 1, "heading": "Food chains", "body": "Energy moves between organisms.", "citation": "ecosystems.txt"}]',
                )
            )
            assessment = Assessment(
                slug="ecosystems-assessment",
                title="Ecosystems Assessment",
                subject_slug="science",
                material_id=material.id,
                created_by=teacher.id,
                status="published",
                attempt_limit=1,
            )
            db.session.add(assessment)
            db.session.flush()
            question = Question(
                assessment_id=assessment.id,
                bloom="Analyze",
                qtype="mcq",
                prompt="Which statement best describes a food chain?",
                options_json='[{"id": "a", "text": "Energy transfer"}, {"id": "b", "text": "Weather"}]',
                answer="a",
                explanation="A food chain shows how energy moves.",
                citation="ecosystems.txt",
            )
            db.session.add(question)
            announcement = Announcement(
                subject="Science",
                title="Science reminder",
                body="Review ecosystems before Friday.",
                teacher_id=teacher.id,
            )
            db.session.add(announcement)
            db.session.commit()
            attempt = Attempt(
                user_id=other.id,
                kind="practice",
                subject_slug="science",
                title="Other student practice",
                score_auto=1,
                score_total_auto=1,
                review_json="[]",
            )
            db.session.add(attempt)
            db.session.commit()
            cls.student_id = student.id
            cls.other_id = other.id
            cls.teacher_id = teacher.id
            cls.admin_id = admin.id
            cls.other_attempt_id = attempt.id
            cls.announcement_id = announcement.id
            cls.question_id = question.id

    def setUp(self):
        self.client = bloom.app.test_client()

    @classmethod
    def tearDownClass(cls):
        with bloom.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        _tmp.cleanup()

    def _csrf(self):
        # Ensure a CSRF token exists in the session (login clears session keys).
        with self.client.session_transaction() as sess:
            token = sess.get("_csrf_token")
            if not token:
                import secrets

                token = secrets.token_urlsafe(32)
                sess["_csrf_token"] = token
            return token

    def _login(self, email, password):
        token = self._csrf()
        return self.client.post(
            "/login",
            data={"email": email, "password": password, "csrf_token": token},
            follow_redirects=False,
        )

    def test_invalid_login(self):
        response = self._login("student@test.local", "wrong-password")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_valid_login(self):
        response = self._login("student@test.local", "student123")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/home", response.headers["Location"])

    def test_admin_can_manage_exam_periods_and_removal_keeps_lessons(self):
        self._login("admin@test.local", "admin123")
        token = self._csrf()
        response = self.client.post(
            "/admin/settings",
            data={"csrf_token": token, "action": "add_term", "name": "Summer"},
        )
        self.assertEqual(response.status_code, 302)
        with bloom.app.app_context():
            term = AcademicTerm.query.filter_by(name="Summer").one()
            material = db.session.get(Material, 1)
            material.term = term.id
            db.session.commit()
            term_id = term.id

        response = self.client.post(
            "/admin/settings",
            data={"csrf_token": token, "action": "rename_term", "term_id": term_id, "name": "Summer Session"},
        )
        self.assertEqual(response.status_code, 302)
        with bloom.app.app_context():
            self.assertEqual(db.session.get(AcademicTerm, term_id).name, "Summer Session")

        response = self.client.post(
            "/admin/settings",
            data={"csrf_token": token, "action": "delete_term", "term_id": term_id},
        )
        self.assertEqual(response.status_code, 302)
        with bloom.app.app_context():
            self.assertIsNone(db.session.get(AcademicTerm, term_id))
            lesson = db.session.get(Material, 1)
            self.assertEqual(lesson.title, "Ecosystems")
            self.assertIsNone(lesson.term)

    def test_student_pages_render_in_shared_shell(self):
        self._login("student@test.local", "student123")
        paths = [
            "/home",
            "/subjects/science",
            "/subjects/science/summaries/ecosystems",
            "/subjects/science/practice/ecosystems",
            "/practice",
            "/results",
            "/profile",
            "/profile/password",
            "/announcements",
            "/messages",
            f"/messages/with/{self.teacher_id}",
            "/assessments/ecosystems-assessment",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'id="main-content"', response.data)
                self.assertIn(b'id="pro-sidebar"', response.data)
                self.assertIn(b'class="skip-link"', response.data)

    def test_assessment_take_requires_post_start(self):
        self._login("student@test.local", "student123")
        blocked = self.client.get("/assessments/ecosystems-assessment/take", follow_redirects=False)
        self.assertEqual(blocked.status_code, 302)
        self.assertIn("/assessments/ecosystems-assessment", blocked.headers["Location"])
        token = self._csrf()
        started = self.client.post(
            "/assessments/ecosystems-assessment/start",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        self.assertEqual(started.status_code, 302)
        self.assertIn("/assessments/ecosystems-assessment/take", started.headers["Location"])
        take = self.client.get("/assessments/ecosystems-assessment/take")
        self.assertEqual(take.status_code, 200)
        self.assertIn(b'id="main-content"', take.data)

    def test_home_removes_duplicate_progress_panels(self):
        self._login("student@test.local", "student123")
        response = self.client.get("/home")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Subject pulse", response.data)
        self.assertNotIn(b"Progress tracker", response.data)
        self.assertIn(b'id="subjects-title">Subjects</h2>', response.data)
        self.assertIn(b"Up next", response.data)
        self.assertIn(b"Avg. score", response.data)

    def test_mobile_drawer_contract_is_rendered(self):
        self._login("student@test.local", "student123")
        response = self.client.get("/home")
        self.assertIn(b'aria-controls="pro-sidebar"', response.data)
        self.assertIn(b'id="pro-sidebar-backdrop"', response.data)

    def test_admin_can_add_course_and_view_its_teacher_and_student_roster(self):
        self._login("admin@test.local", "admin123")
        token = self._csrf()
        added = self.client.post("/admin/section", data={
            "csrf_token": token,
            "action": "course",
            "course_name": "Civics",
        })
        self.assertEqual(added.status_code, 302)
        with bloom.app.app_context():
            year = SchoolYear(name="2098-2099", active=False)
            db.session.add(year)
            db.session.flush()
            section = SchoolSection(name="Civics Test", grade=7, school_year_id=year.id)
            teacher = User(email="civics.teacher@test.local", name="Civics Teacher", role="teacher", subject="Civics", password_hash=generate_password_hash("teacher123"))
            student = User(email="civics.student@test.local", name="Civics Student", role="student", password_hash=generate_password_hash("student123"))
            db.session.add_all([section, teacher, student])
            db.session.flush()
            student.section = section.name
            student.section_id = section.id
            teacher_id, section_id = teacher.id, section.id
            db.session.commit()
        assigned = self.client.post("/admin/section", data={
            "csrf_token": self._csrf(),
            "action": "course_assignment",
            "course_name": "Civics",
            "teacher_id": str(teacher_id),
            "section_id": str(section_id),
        })
        self.assertEqual(assigned.status_code, 302)
        page = self.client.get("/admin/section")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Academic Setup", page.data)
        self.assertIn(b"Civics", page.data)
        self.assertIn(b"Civics Teacher", page.data)
        self.assertIn(b"Civics Student", page.data)
        self.client.post("/logout", data={"csrf_token": self._csrf()})
        self._login("civics.student@test.local", "student123")
        home = self.client.get("/home")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Civics", home.data)
        subject_page = self.client.get("/subjects/civics")
        self.assertEqual(subject_page.status_code, 200)

    def test_announcement_get_is_read_only(self):
        self._login("student@test.local", "student123")
        response = self.client.get(f"/announcements/{self.announcement_id}")
        self.assertEqual(response.status_code, 200)
        with bloom.app.app_context():
            read = AnnouncementRead.query.filter_by(
                user_id=self.student_id,
                announcement_id=self.announcement_id,
            ).first()
            self.assertIsNone(read)

    def test_announcement_post_marks_read(self):
        self._login("student@test.local", "student123")
        token = self._csrf()
        response = self.client.post(
            f"/announcements/{self.announcement_id}/read",
            data={"csrf_token": token},
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        with bloom.app.app_context():
            read = AnnouncementRead.query.filter_by(
                user_id=self.student_id,
                announcement_id=self.announcement_id,
            ).first()
            self.assertIsNotNone(read)

    def test_message_send_json_contract(self):
        self._login("student@test.local", "student123")
        token = self._csrf()
        response = self.client.post(
            f"/messages/with/{self.teacher_id}",
            data={"body": "Can you explain food chains?", "csrf_token": token},
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["message"]["body"], "Can you explain food chains?")

    def test_assessment_submit_flow(self):
        self._login("other@test.local", "student123")
        token = self._csrf()
        start = self.client.post(
            "/assessments/ecosystems-assessment/start",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        self.assertEqual(start.status_code, 302)
        take = self.client.get("/assessments/ecosystems-assessment/take")
        self.assertEqual(take.status_code, 200)
        token = self._csrf()
        response = self.client.post(
            "/assessments/ecosystems-assessment/submit",
            data={f"q{self.question_id}": "a", "csrf_token": token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/results/", response.headers["Location"])

    def test_csrf_rejects_bare_post(self):
        self._login("student@test.local", "student123")
        response = self.client.post("/logout", data={}, follow_redirects=False)
        self.assertIn(response.status_code, {302, 400})

    def test_student_cannot_view_other_attempt(self):
        self._login("student@test.local", "student123")
        response = self.client.get(f"/results/{self.other_attempt_id}", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/results") or "/results" in response.headers["Location"])

    def test_teacher_subject_scoped_attempt(self):
        self._login("teacher@test.local", "teacher123")
        response = self.client.get(f"/results/{self.other_attempt_id}", follow_redirects=False)
        # Science teacher may view science attempt owned by a student.
        self.assertEqual(response.status_code, 200)

    def test_student_blocked_from_teacher_home(self):
        self._login("student@test.local", "student123")
        response = self.client.get("/teacher", follow_redirects=False)
        self.assertIn(response.status_code, {302, 403})

    def test_teacher_monitor_lists_student_progress(self):
        self._login("teacher@test.local", "teacher123")
        response = self.client.get("/teacher/monitor")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="pro-sidebar"', response.data)
        self.assertIn(b"Other Student", response.data)
        self.assertIn(b"avg score", response.data)
        self.assertIn(b"/results/", response.data)

    def test_teacher_reviews_file_and_deploys_summary(self):
        upload_dir = bloom.app.config["UPLOAD_FOLDER"]
        os.makedirs(upload_dir, exist_ok=True)
        stored = "20260101120000_backup.txt"
        path = os.path.join(upload_dir, stored)
        with bloom.app.app_context():
            student = db.session.get(User, self.student_id)
            material = Material(
                slug="student-backup",
                title="Student backup",
                subject_slug="science",
                owner_id=student.id,
                source="student",
                status="pending",
                filename=stored,
                extracted_text="Energy moves through food chains.",
            )
            db.session.add(material)
            db.session.flush()
            db.session.add(
                Summary(
                    material_id=material.id,
                    intro="A short backup summary.",
                    sections_json='[{"id": "s1", "heading": "Energy", "body": "Energy moves.", "citation": "p. 1"}]',
                )
            )
            db.session.commit()
            material_id = material.id
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Energy moves through food chains.")
        try:
            self._login("teacher@test.local", "teacher123")
            materials = self.client.get("/teacher/materials")
            self.assertEqual(materials.status_code, 200)
            self.assertIn(b"Pending review", materials.data)
            self.assertIn(b"Student backup", materials.data)
            review = self.client.get(f"/teacher/materials/{material_id}")
            self.assertEqual(review.status_code, 200)
            self.assertIn(b"A short backup summary.", review.data)
            self.assertIn(b"Open uploaded file", review.data)
            self.assertIn(b"Deploy to students", review.data)
            file_resp = self.client.get(f"/teacher/materials/{material_id}/file")
            self.assertEqual(file_resp.status_code, 200)
            self.assertIn(b"Energy moves through food chains.", file_resp.data)
            file_resp.close()
            token = self._csrf()
            deploy = self.client.post(
                f"/teacher/materials/{material_id}",
                data={"action": "approve", "csrf_token": token},
                follow_redirects=False,
            )
            self.assertEqual(deploy.status_code, 302)
            with bloom.app.app_context():
                self.assertEqual(db.session.get(Material, material_id).status, "approved")
            with self.client.session_transaction() as sess:
                sess.clear()
            self._login("student@test.local", "student123")
            blocked = self.client.get(f"/teacher/materials/{material_id}/file", follow_redirects=False)
            self.assertIn(blocked.status_code, {302, 403})
            visible = self.client.get("/subjects/science/summaries/student-backup")
            self.assertEqual(visible.status_code, 200)
            self.assertIn(b"A short backup summary.", visible.data)
        finally:
            if os.path.isfile(path):
                os.remove(path)

    def test_other_subject_teacher_cannot_open_material(self):
        with bloom.app.app_context():
            english = User(
                email="english@test.local",
                name="English Teacher",
                role="teacher",
                subject="English",
                password_hash=generate_password_hash("teacher123"),
            )
            db.session.add(english)
            db.session.commit()
            material = Material.query.filter_by(slug="ecosystems").first()
            material_id = material.id
        self._login("english@test.local", "teacher123")
        review = self.client.get(f"/teacher/materials/{material_id}", follow_redirects=False)
        self.assertEqual(review.status_code, 302)
        self.assertIn("/teacher/materials", review.headers["Location"])
        file_resp = self.client.get(f"/teacher/materials/{material_id}/file", follow_redirects=False)
        self.assertEqual(file_resp.status_code, 404)

    def test_user_can_upload_profile_photo(self):
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc``\x00\x00"
            b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        self._login("student@test.local", "student123")
        token = self._csrf()
        upload = self.client.post(
            "/profile",
            data={"action": "photo", "csrf_token": token, "photo": (BytesIO(png), "me.png")},
            follow_redirects=False,
        )
        self.assertEqual(upload.status_code, 302)
        photo = self.client.get(f"/users/{self.student_id}/photo")
        self.assertEqual(photo.status_code, 200)
        self.assertTrue(photo.data.startswith(b"\x89PNG"))
        photo.close()
        page = self.client.get("/profile")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"/users/", page.data)
        self.assertIn(b"is-photo", page.data)
        with self.client.session_transaction() as sess:
            sess.clear()
        blocked = self.client.get(f"/users/{self.student_id}/photo", follow_redirects=False)
        self.assertIn(blocked.status_code, {302, 401, 403})

    def test_logout_get_does_not_clear_session(self):
        self._login("student@test.local", "student123")
        response = self.client.get("/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), self.student_id)

    def test_logout_post_clears_session(self):
        self._login("student@test.local", "student123")
        token = self._csrf()
        response = self.client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))


if __name__ == "__main__":
    unittest.main()
