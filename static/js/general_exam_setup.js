(() => {
  const form = document.querySelector("[data-general-exam-builder]");
  if (!form) return;

  const totalQuestions = Number(form.dataset.questionTotal || 30);
  const status = form.querySelector("[data-count-status]");
  const submit = form.querySelector(".general-exam-submit");
  const modeInputs = [...form.querySelectorAll('input[name="distribution"]')];
  const subjectCards = [...form.querySelectorAll("[data-subject-card]")];

  const selectedCards = () => subjectCards.filter((card) =>
    card.querySelector("[data-subject-toggle]")?.checked
  );

  function evenCounts(cards) {
    if (!cards.length) return [];
    const base = Math.floor(totalQuestions / cards.length);
    const remainder = totalQuestions % cards.length;
    return cards.map((_, index) => base + (index < remainder ? 1 : 0));
  }

  function sync() {
    const cards = selectedCards();
    const isCustom = form.querySelector('input[name="distribution"]:checked')?.value === "custom";
    const even = evenCounts(cards);

    subjectCards.forEach((card) => {
      const slug = card.dataset.subjectCard;
      const active = cards.includes(card);
      const countInput = card.querySelector("[data-question-count]");
      const countWrap = card.querySelector("[data-question-count-wrap]");
      const badge = card.querySelector("[data-subject-count]");
      const lessonBoxes = [...card.querySelectorAll("[data-lesson-subject]")];
      const chosenLessons = lessonBoxes.filter((box) => box.checked).length;
      const index = cards.indexOf(card);
      countWrap.hidden = !active;
      countInput.disabled = !active || !isCustom;
      if (active && !isCustom) countInput.value = even[index];
      badge.textContent = active
        ? `${countInput.value} question${Number(countInput.value) === 1 ? "" : "s"}`
        : "Not selected";
      card.classList.toggle("is-selected", active);
      card.classList.toggle("has-lessons", chosenLessons > 0);
      card.setAttribute("data-subject-slug", slug);
    });

    const counts = cards.map((card) => Number(card.querySelector("[data-question-count]").value));
    const currentTotal = counts.reduce((sum, count) => sum + (Number.isFinite(count) ? count : 0), 0);
    const hasLessons = cards.length > 0 && cards.every((card) =>
      card.querySelectorAll("[data-lesson-subject]:checked").length > 0
    );
    const valid = hasLessons && currentTotal === totalQuestions && counts.every((count) => count >= 1);

    status.textContent = !cards.length
      ? "Select at least one subject and lesson."
      : !hasLessons
        ? "Choose at least one lesson for every selected subject."
        : `${currentTotal} of ${totalQuestions} questions assigned${valid ? " · Ready to generate" : " · Counts must total 30"}.`;
    status.classList.toggle("is-valid", valid);
    status.classList.toggle("is-invalid", !valid);
    submit.disabled = form.dataset.canGenerate !== "true" || !valid;
  }

  form.dataset.canGenerate = String(!submit.disabled);
  form.addEventListener("change", (event) => {
    const card = event.target.closest("[data-subject-card]");
    if (event.target.matches("[data-lesson-subject]")) {
      const subjectCard = event.target.closest("[data-subject-card]");
      const toggle = subjectCard.querySelector("[data-subject-toggle]");
      toggle.checked = subjectCard.querySelectorAll("[data-lesson-subject]:checked").length > 0;
    }
    if (event.target.matches("[data-subject-toggle]") && card) {
      if (!event.target.checked) {
        card.querySelectorAll("[data-lesson-subject]").forEach((lesson) => { lesson.checked = false; });
      } else if (!card.querySelector("[data-lesson-subject]:checked")) {
        const firstLesson = card.querySelector("[data-lesson-subject]");
        if (firstLesson) firstLesson.checked = true;
      }
    }
    if (event.target.matches('input[name="distribution"]')) {
      const cards = selectedCards();
      const values = evenCounts(cards);
      cards.forEach((subjectCard, index) => {
        subjectCard.querySelector("[data-question-count]").value = values[index];
      });
    }
    sync();
  });

  form.addEventListener("input", (event) => {
    if (event.target.matches("[data-question-count]")) {
      const subjectCard = event.target.closest("[data-subject-card]");
      subjectCard.querySelector("[data-subject-count]").textContent = `${event.target.value} question${Number(event.target.value) === 1 ? "" : "s"}`;
      const selected = form.querySelector('input[name="distribution"][value="custom"]');
      selected.checked = true;
      sync();
    }
  });

  form.addEventListener("submit", (event) => {
    sync();
    if (submit.disabled) {
      event.preventDefault();
      status.focus?.();
    }
  });
  sync();
})();
