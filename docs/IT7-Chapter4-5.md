# CHAPTER IV
# RESULTS AND DISCUSSION

This chapter presents the results of developing and testing **Bloom**, the AI-powered smart study assistant for HOTS-based assessment generation and learning support. Following the Handbook for Undergraduate Student Research Program, the discussion covers activities from the **development phase** through the **testing phase** of the software development life cycle (SDLC). The development phase describes the implemented system with screenshots. The testing phase reports unit testing, integration testing, system testing, and user acceptance testing.

Bloom was implemented as a web application using Python, Flask with SQLAlchemy, PostgreSQL for deployment, SQLite for isolated automated tests, and the Google Gemini API (with an optional OpenAI fallback). Teachers upload lesson materials, generate HOTS items at Analyze, Evaluate, and Create, and publish assessments. Students read grounded summaries, take guided practice, complete published assessments, and view feedback. An administrator manages users and pilot settings. All generated classroom items remain under teacher review before students use them.

---

## A. Development Phase

The development phase produced a working prototype for a Grade 7 pilot in English, Mathematics, and Science at Letran Calamba Junior High School. The system uses role-based access (`student`, `teacher`, `admin`), session authentication, CSRF protection on form posts, and an AI module that summarizes uploaded lesson text and generates HOTS questions from that text only.

The figures below use the original 1280-pixel screen captures in `docs/audit-screenshots`; the image links keep the source screenshots at full resolution rather than embedding compressed thumbnails. When placing them in the final Word/PDF manuscript, keep each screenshot large enough for labels and controls to remain readable.

### Login and role-based access

Users sign in with school email and password. A valid student account is redirected to the student home; a teacher is redirected to the teacher workspace; an administrator is redirected to the admin home. An invalid password returns the user to the login page. Logout is confirmed on a GET page and completed only by POST so that browser prefetch cannot sign a user out by accident.

**Figure 8.** Login page of Bloom  
![Bloom screen: 01 login](audit-screenshots/01-login.png)

The login screen is the single entry point for all roles. This supports the study’s requirement that Bloom be used as a school system, not as an open public chatbot.

### Student module

After login, the student home presents subjects (English, Mathematics, Science), a short “Do this next” queue, and practice averages. Navigation is shared across student pages: Home, Practice, Results, Announcements, Messages, and Profile.

**Figure 9.** Student home  
![Bloom screen: 02 home](audit-screenshots/02-home.png)

The subject hub is the lesson workspace for one subject. Students open approved summaries, start practice, and (when the teacher allows) upload a backup file that stays pending until the teacher deploys it. This keeps student-uploaded files from reaching the class until a teacher reviews them.

**Figure 10.** Subject hub (Science)  
![Bloom screen: 08 subject hub](audit-screenshots/08-subject-hub.png)

Approved lesson text is turned into a short, student-friendly summary. The summarizer is instructed to use only the uploaded lesson, which addresses the problem that generic AI tools often add outside facts that are not in the school material.

**Figure 11.** Lesson summary reader  
![Bloom screen: 10 summary](audit-screenshots/10-summary.png)

Guided practice is the student HOTS loop. The learner sets difficulty (easy, medium, hard), Bloom focus (Analyze, Evaluate, Create, or mixed), item count, and question types, then generates a practice set. Difficulty is designed to change complexity, not to drop the item below Analyze–Evaluate–Create.

**Figure 12.** Practice library  
![Bloom screen: 03 practice](audit-screenshots/03-practice.png)

**Figure 13.** Practice setup  
![Bloom screen: 09 practice setup](audit-screenshots/09-practice-setup.png)

**Figure 14.** Practice take  
![Bloom screen: 15 practice take](audit-screenshots/15-practice-take.png)

After submission, Bloom stores an attempt and shows a result review (score for auto-scored items, explanations when released). Assessment attempts are started by POST so that opening a link cannot silently consume an attempt.

**Figure 15.** Results history  
![Bloom screen: 04 results](audit-screenshots/04-results.png)

**Figure 16.** Result review  
![Bloom screen: 13 result review](audit-screenshots/13-result-review.png)

Announcements and messages support learning beyond the quiz itself. Teachers post subject announcements; students mark them read. Students may start a conversation with their subject teacher.

**Figure 17.** Announcements  
![Bloom screen: 05 announcements](audit-screenshots/05-announcements.png)

**Figure 18.** Messages inbox  
![Bloom screen: 06 messages](audit-screenshots/06-messages.png)

**Figure 19.** Message thread  
![Bloom screen: 12 messages thread](audit-screenshots/12-messages-thread.png)

The profile page lets the student update a photo and password. Photo files are stored on the server and are not shown to users who are not signed in.

**Figure 20.** Student profile  
![Bloom screen: 07 profile](audit-screenshots/07-profile.png)

### Teacher module

The teacher home is scoped to the teacher’s subject. From here the teacher manages materials, generates HOTS items, monitors attempts, and posts announcements.

**Figure 21.** Teacher home  
![Bloom screen: 14 teacher home](audit-screenshots/14-teacher-home.png)

On Materials, the teacher uploads a PDF, DOCX, PPTX, or TXT file. The system extracts text, builds a summary, and keeps student backup uploads in **Pending review** until the teacher deploys or rejects them. A teacher of another subject cannot open another subject’s file.

**Figure 22.** Teacher materials  
![Bloom screen: 19 teacher materials](audit-screenshots/19-teacher-materials.png)

The HOTS workspace generates Analyze, Evaluate, Create, or mixed items from the lesson text. The teacher can review, edit, and publish or close an assessment, and can control whether scores, answers, and feedback are released to students. This is the main validation mechanism of the study: AI drafts items; the teacher decides what the class sees.

**Figure 23.** Teacher HOTS generation  
![Bloom screen: 16 teacher hots](audit-screenshots/16-teacher-hots.png)

Monitor shows section progress (attempts and average scores) and links to student results. Announce lets the teacher post reminders for the subject.

**Figure 24.** Teacher monitor  
![Bloom screen: 17 teacher monitor](audit-screenshots/17-teacher-monitor.png)

**Figure 25.** Teacher announcements  
![Bloom screen: 18 teacher announce](audit-screenshots/18-teacher-announce.png)

**Figure 26.** Teacher messages  
![Bloom screen: 21 teacher messages](audit-screenshots/21-teacher-messages.png)

### Admin module

The administrator home supports the Grade 7 pilot: user accounts, section view, reports snapshot, and settings such as upload limits. Bloom authenticates with school email, so admin enrollment is required before classroom UAT.

**Figure 27.** Admin home  
![Bloom screen: 22 admin home](audit-screenshots/22-admin-home.png)

The current screenshot set documents the main student and teacher workflows and the admin home. It does not yet show every current admin workflow, including section management, school-year setup, user management, and general settings. Add updated captures of those screens before describing the documentation as complete.

### Development outcome

At the end of development, Bloom implements the four specific objectives at prototype level: (1) HOTS generation guided by Bloom’s Taxonomy and uploaded curriculum text; (2) filtering through prompt rules, Bloom tags, and teacher approval; (3) a student module with summaries, practice, assessments, and feedback; and (4) instruments for evaluating usability and quality (ISO evaluation forms and adapted SUS questionnaires). The remaining work in this chapter is to show that those parts were tested.

---

## B. Testing Phase

Testing followed four levels required by the handbook: **unit testing**, **integration testing**, **system testing**, and **user acceptance testing**. The automated Python suite contains 7 focused math-rendering unit tests and 20 application smoke and workflow tests; all **27 tests passed** on the development machine. A separate k6 stress run exercised the public login page with up to 200 virtual users. That run is supplementary performance evidence and does not replace UAT. User acceptance testing uses the ISO/IEC 25010:2023 product quality model, the ISO/IEC 25019:2023 quality-in-use model, ISO/IEC 25040:2024 as the evaluation process, and an adapted System Usability Scale (SUS).

Legend for functional tables: **Passed** = actual result matched the expected result.

### 1. Unit testing

Unit tests checked isolated behavior. Seven standalone math-rendering tests cover fractions, mixed numbers, repeating decimals, equation runs, prose preservation, and safe escaping. The focused access-rule cases below check login, logout, CSRF, role, and result ownership behavior; module-to-module workflows are reported separately under integration testing.

**Table 4.1**  
*Unit test cases of Bloom*

| Test ID | Condition | Expected result | Actual result | Status |
|---|---|---|---|---|
| UT-01 | Valid student email and password | Redirect to `/home` | Redirected to `/home` | Passed |
| UT-02 | Wrong password | Remain on login | Redirected to `/login` | Passed |
| UT-03 | GET `/logout` | Session still active (confirm page only) | `user_id` still in session | Passed |
| UT-04 | POST `/logout` with CSRF token | Session cleared | `user_id` cleared | Passed |
| UT-05 | POST without CSRF token | Request rejected | Status 302 or 400 | Passed |
| UT-06 | Student opens `/teacher` | Access denied | 302 or 403 | Passed |
| UT-07 | Student opens another student’s result | Access denied | Redirected to `/results` | Passed |

All seven focused access-rule cases passed. The separate math-rendering unit tests also passed, including checks that ordinary prose remains unchanged and generated text is escaped before rendering. Together these tests show that the rules work before larger user workflows are considered.

### 2. Integration testing

Integration tests checked joined modules: assessment start and submit, teacher review and deploy, announcements, messages, profile photo, and teacher monitor.

**Table 4.2**  
*Integration test cases of Bloom*

| Test ID | Modules joined | Expected result | Actual result | Status |
|---|---|---|---|---|
| IT-01 | Login + assessment start | GET `/take` blocked until POST `/start` | GET redirected to lobby; POST opened take page | Passed |
| IT-02 | Assessment take + submit + results | Submit stores attempt and redirects to result | Redirected to `/results/…` | Passed |
| IT-03 | Materials + summary + student hub | Teacher approve deploys summary; student can read it; student cannot download teacher file route | Status became `approved`; student saw summary; file route blocked | Passed |
| IT-04 | English teacher + Science material | Other-subject teacher cannot review or download the file | Redirect / 404 | Passed |
| IT-05 | Announcement + read tracking | GET does not mark read; POST marks read | GET left unread; POST created `AnnouncementRead` | Passed |
| IT-06 | Messages + JSON send | Student message saved and returned | JSON `ok` with message body | Passed |
| IT-07 | Profile + photo + auth | Logged-in user sees photo; logged-out request blocked | PNG served when logged in; 302/401/403 when logged out | Passed |
| IT-08 | Teacher monitor + student attempts | Monitor lists the student and score | “Other Student”, avg score, and result link shown | Passed |
| IT-09 | Teacher + student attempt | Subject teacher may open the student’s Science attempt | HTTP 200 | Passed |

The critical academic path is covered here: a teacher can deploy a lesson, a student can practice or take an assessment, and results stay inside the right role and subject.

### 3. System testing

System testing checked Bloom as one application: shared student shell, core pages rendering, and the mobile drawer contract.

**Table 4.3**  
*System test cases of Bloom*

| Test ID | Scope | Expected result | Actual result | Status |
|---|---|---|---|---|
| ST-01 | Student pages (home, subject, summary, practice, results, profile, announcements, messages, assessment lobby) | Each page returns 200 and includes main content, sidebar, and skip link | All listed paths returned 200 with those landmarks | Passed |
| ST-02 | Student home composition | Home shows subjects and next actions; old duplicate progress panels are gone | “Subjects” and “Up next” present; “Subject pulse” / “Progress tracker” absent | Passed |
| ST-03 | Mobile navigation | Menu controls the sidebar | `aria-controls="pro-sidebar"` and backdrop rendered | Passed |
| ST-04 | Automated suite | All automated tests pass | 27 tests, 0 failures (6.82 s) | Passed |

System testing confirms that the student learning loop and teacher support screens run together under one login model, one database, and one UI shell for students.

### Supplementary performance and stress testing

A bounded k6 run measured how the deployed application served its public login page under concurrent read-only traffic. The scenario ramped from no users to 50 and then 200 virtual users, held the peak briefly, and ramped down. It requested only `GET /login`; it did not authenticate users, submit forms, call AI providers, or write to PostgreSQL. Therefore, the results describe login-page response under this workload and should not be interpreted as a full database, authenticated-session, or whole-system capacity test.

**Table 4.4**  
*k6 login-page stress test results*

| Measure | Result | Acceptance target | Outcome |
|---|---:|---:|---|
| Peak concurrent virtual users | 200 | 200 | Reached |
| Total requests | 6,958 | — | — |
| Failed requests | 0 (0%) | Less than 2% | Passed |
| Checks | 13,916 passed | All checks pass | Passed |
| Average response time | 234.19 ms | — | — |
| 95th percentile response time | 285.32 ms | Below 2,500 ms | Passed |
| Maximum response time | 1.11 s | — | — |
| Throughput | 114.57 requests/second | — | — |

The run completed on November 18, 2026 against the deployed login page. It reached 200 virtual users, returned HTTP 200 responses with the expected email field, and met both configured thresholds. The reusable scenario is in `tests/k6_login_stress.js`. To reproduce it, install k6 and run `k6 run --env BASE_URL=https://capstoned-production-0585.up.railway.app tests/k6_login_stress.js`. This is a read-only page-load test; add authenticated, database-backed scenarios before making claims about capacity for signed-in workflows or PostgreSQL writes.

### 4. User acceptance testing

User acceptance testing (UAT) evaluates whether teachers and students can use Bloom in the Grade 7 pilot context. UAT follows **ISO/IEC 25040:2024**: define the evaluation, design the instrument, plan the session, execute, and conclude.

**Instruments (appendices)**  
- Teacher Evaluation Form and Student Evaluation Form — all nine product-quality characteristics of **ISO/IEC 25010:2023** and all three quality-in-use characteristics of **ISO/IEC 25019:2023** (one item each; 5-point Likert scale).  
- Teacher Questionnaire and Student Questionnaire — respondent profile, adapted SUS (10 items), and open questions on HOTS and curriculum support.

**Scale for ISO items**

| Mean | Verbal interpretation |
|---|---|
| 4.21 – 5.00 | Strongly agree / Excellent |
| 3.41 – 4.20 | Agree / Very satisfactory |
| 2.61 – 3.40 | Neutral / Satisfactory |
| 1.81 – 2.60 | Disagree / Fair |
| 1.00 – 1.80 | Strongly disagree / Poor |

**Table 4.5**  
*ISO/IEC 25010:2023 product quality — UAT tally sheet*  
*(Compute the mean per item after the pilot. Do not invent scores.)*

| # | Characteristic | Teacher mean | Student mean | Interpretation |
|---|---|---|---|---|
| 1 | Functional suitability |  |  |  |
| 2 | Performance efficiency |  |  |  |
| 3 | Compatibility |  |  |  |
| 4 | Interaction capability |  |  |  |
| 5 | Reliability |  |  |  |
| 6 | Security |  |  |  |
| 7 | Maintainability |  |  |  |
| 8 | Flexibility |  |  |  |
| 9 | Safety |  |  |  |
| | **Overall product quality** |  |  |  |

**Table 4.6**  
*ISO/IEC 25019:2023 quality in use — UAT tally sheet*

| # | Characteristic | Teacher mean | Student mean | Interpretation |
|---|---|---|---|---|
| 10 | Beneficialness |  |  |  |
| 11 | Freedom from risk |  |  |  |
| 12 | Acceptability |  |  |  |
| | **Overall quality in use** |  |  |  |

**Table 4.7**  
*Adapted SUS (0–100) — UAT tally sheet*

| Group | n | SUS mean | Remarks |
|---|---|---|---|
| Teachers |  |  | Odd items: rating − 1; even items: 5 − rating; sum × 2.5 |
| Students |  |  | Same formula |
| Combined |  |  |  |

### Interpreting the lowest ratings

The panel comment sheet reports a weighted mean of **4.00** for functional suitability and performance efficiency. Under the study's interpretation scale, 4.00 falls in **Agree / Very satisfactory** (3.41–4.20). These are positive results that were lower relative to the other dimensions; they should not be described as poor or unsatisfactory.

A numeric mean alone does not reveal why respondents chose their ratings. Use the open-ended responses, if collected, to support the explanation. If those comments point to a gap, functional suitability may be discussed in terms of how completely the available features support users' tasks and how easy it is to find or understand those features. Performance efficiency may be discussed in terms of perceived responsiveness during page loads and AI generation. Panel feedback raised internet connectivity and external AI service delays as possible concerns, but the survey does not establish that either caused the 4.00 rating. Present these as possible context, not proven causes, unless respondent comments or timing measurements confirm them.

**How to finish this subsection after the pilot**

1. Encode Likert answers in a spreadsheet.  
2. Fill Tables 4.5–4.7.  
3. Add one short paragraph under each table (what was strong, what to fix).  
4. Quote two or three open-question themes (time saved, HOTS quality, confusing screens).  
5. Do not add new tables in Chapter V.

Until those means are collected, acceptance by teachers and students remains the outstanding UAT result. The automated tests establish functional correctness for the tested paths, while the k6 result is limited to read-only login-page performance at the stated workload.

The practice-generation limit is **three successful generations per student, per subject, per day**, resetting at midnight Philippine time. AI API charges depend on input and output token use rather than a flat amount per practice set. The cost assumptions, configured models, and provider references are documented in [`AI_USAGE_AND_LIMITS.md`](AI_USAGE_AND_LIMITS.md); recheck provider rates and model status before final submission because both can change.

---

# CHAPTER V
# SUMMARY, CONCLUSION, AND RECOMMENDATIONS

This chapter summarizes the significant findings of the study, states the conclusions in relation to those findings, and offers recommendations for the school and for future researchers. In line with the handbook, this chapter does not present new tables or figures. Four corollary questions were stated in Chapter I; four findings are summarized below. After the Grade 7 UAT, replace any sentence marked **[after UAT]** with the actual verbal interpretation from Tables 4.5–4.7.

## Summary of Significant Findings

**Finding 1 (corollary question 1).** Teachers face a heavy load when they must write curriculum-aligned HOTS items by hand. The developed teacher module shows a practical response: upload the lesson, generate Analyze / Evaluate / Create items from that text, review them, and publish only what the teacher accepts. Development and integration tests confirmed that pending student uploads do not reach the class until a teacher deploys them.

**Finding 2 (corollary question 2).** Generic AI tools fail classroom alignment when they are not grounded in the school’s lesson and not constrained to higher-order levels. Bloom’s prompts require Grade 7 subject context, use only extracted lesson text, keep difficulty from changing the Bloom level, and tag items as Analyze, Evaluate, or Create. Teacher review remains the final filter.

**Finding 3 (corollary question 3).** Students have limited structured practice for higher-order thinking beyond class recitation. The student module supplies approved summaries, configurable HOTS practice, published assessments, results, announcements, and a channel to ask the teacher. System tests showed these pages load in one shared student shell with role and attempt ownership checks.

**Finding 4 (corollary question 4).** An AI study assistant can support teachers when it drafts items and summaries but does not replace professional judgment. Monitor, release flags for scores/answers/feedback, and subject-scoped access keep the teacher in control. **[after UAT]** Teachers’ beneficialness, acceptability, and SUS scores will state how far this help is accepted in the real Grade 7 context.

Across automated testing, **27 of 27** cases passed: 7 isolated math-rendering unit tests and 20 application smoke and workflow tests covering login, CSRF, roles, assessment flow, material deployment, messages, announcements, profile photos, and monitoring. In the supplementary k6 run, the login page served 6,958 requests with no failures at up to 200 virtual users; the 95th percentile response time was 285.32 ms. These performance results cover only the public login page and do not establish authenticated or database-backed capacity. **[after UAT]** Insert one sentence on overall ISO product quality, quality in use, and SUS.

## Conclusions

1. Bloom can be designed and implemented as a school web system that generates HOTS-focused assessments from uploaded Junior High materials, using prompt engineering and Bloom’s Taxonomy (Analyze, Evaluate, Create), which meets the first specific objective.

2. Filtering and validation can be implemented as prompt constraints, Bloom-level tagging, and teacher review/approval workflows. Tests showed that undeployed materials stay pending, other-subject teachers cannot open another subject’s files, and students cannot open teacher routes or other students’ results. This meets the second specific objective at prototype level.

3. A student-centered support module can provide summaries, guided practice, assessments, and feedback inside one login. This meets the third specific objective.

4. Usability and effectiveness can be evaluated with ISO/IEC 25010:2023, ISO/IEC 25019:2023, ISO/IEC 25040:2024, and adapted SUS. Functional testing is complete. **[after UAT]** Acceptance by teachers and students should be stated here using the verbal interpretations from Chapter IV, not new tables.

5. Therefore, an intelligent, curriculum-aligned system can assist Letran Calamba teachers and students by grounding AI in uploaded lessons, keeping HOTS levels explicit, and leaving publication to the teacher. It does not replace classroom teaching or long-term measurement of achievement, which remain outside the scope of this prototype.

## Recommendations

Based on the conclusions, the researchers recommend the following.

**For teachers.** Use Bloom as a drafting and practice tool. Always review AI items before publish. Release scores and answers only when the class is ready.

**For the Junior High School and MIS.** Complete the limited Grade 7 email enrollment so classroom UAT can be finished; keep the prototype off full institutional deployment until privacy, consent, and support are in place.

**For administrators of Bloom.** Keep role separation and teacher approval as default. Do not enable student-facing AI output that skipped review.

**For improvement of the system.** (1) Finish Grade 7 UAT and encode Tables 4.5–4.7. (2) Capture assessment lobby and assessment-take screenshots for the final manuscript if they were missing in the first screenshot set. (3) Strengthen production configuration (secrets, seed accounts, API key handling). (4) Deepen admin reports if the school expands beyond one section. (5) Unify teacher and student visual shells so staff pages match the student interface.

**For future researchers.** Replicate the study in other grades or subjects; add a true pre-test/post-test of HOTS achievement if the research question is learning gain rather than system quality; or compare Bloom-generated items with teacher-written items using a HOTS quality rubric. Do not treat this prototype as evidence of long-term academic achievement.

---

## Researcher notes (remove before printing)

- Insert the PNG files listed under each figure.  
- Run UAT, then delete every **[after UAT]** marker.  
- Chapter V must stay without tables or figures.  
- Copy this chapter after Chapter III in the official thesis Word file.  
- Appendices: evaluation forms, questionnaires, and an optional automated test report. Reproduce the Python suite with `python -m unittest discover -v`. Reproduce the read-only login stress test with `k6 run --env BASE_URL=https://capstoned-production-0585.up.railway.app tests/k6_login_stress.js`.
