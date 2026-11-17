(() => {
  const cards = Array.from(document.querySelectorAll(".take-card"));
  const prevBtn = document.getElementById("prev-btn");
  const nextBtn = document.getElementById("next-btn");
  const submitBtn = document.getElementById("submit-btn");
  const progressText = document.getElementById("progress-text");
  const progressBar = document.getElementById("progress-bar");
  const steps = Array.from(document.querySelectorAll(".take-step"));
  const form = document.getElementById("practice-take-form");
  if (!cards.length || !form) return;

  let index = 0;
  let dirty = false;
  const draftKey =
    form.getAttribute("data-draft-key") ||
    `bloom-take:${form.getAttribute("action") || location.pathname}`;

  const answered = (card) => {
    const checked = card.querySelector("input[type=radio]:checked");
    const textarea = card.querySelector("textarea");
    if (card.querySelector("input[type=radio]")) return Boolean(checked);
    if (textarea) return textarea.value.trim().length > 0;
    return true;
  };

  const unansweredCount = () => cards.filter((card) => !answered(card)).length;

  const collectDraft = () => {
    const values = {};
    form.querySelectorAll("input[type=radio]:checked, textarea").forEach((field) => {
      if (!field.name) return;
      values[field.name] = field.value;
    });
    return values;
  };

  const saveDraft = () => {
    try {
      localStorage.setItem(draftKey, JSON.stringify({ savedAt: Date.now(), values: collectDraft() }));
    } catch (_error) {
      /* ignore quota / private mode */
    }
  };

  const restoreDraft = () => {
    try {
      const raw = localStorage.getItem(draftKey);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      const values = parsed?.values || {};
      Object.entries(values).forEach(([name, value]) => {
        const radios = form.querySelectorAll(`input[type=radio][name="${CSS.escape(name)}"]`);
        if (radios.length) {
          radios.forEach((radio) => {
            radio.checked = radio.value === value;
          });
          return;
        }
        const area = form.querySelector(`textarea[name="${CSS.escape(name)}"]`);
        if (area) area.value = value;
      });
    } catch (_error) {
      /* ignore */
    }
  };

  const clearDraft = () => {
    try {
      localStorage.removeItem(draftKey);
    } catch (_error) {
      /* ignore */
    }
  };

  const progressTrack = document.querySelector(".take-progress");

  const syncNav = () => {
    prevBtn.disabled = index === 0;
    const last = index === cards.length - 1;
    nextBtn.hidden = last;
    submitBtn.hidden = !last;
  };

  const show = (nextIndex) => {
    cards[index].hidden = true;
    cards[index].classList.remove("is-active");
    index = nextIndex;
    cards[index].hidden = false;
    cards[index].classList.add("is-active");

    progressText.textContent = String(index + 1);
    progressBar.style.width = `${((index + 1) / cards.length) * 100}%`;
    if (progressTrack) progressTrack.setAttribute("aria-valuenow", String(index + 1));
    steps.forEach((step, stepIndex) => {
      step.classList.toggle("is-current", stepIndex === index);
      step.classList.toggle("is-done", stepIndex < index);
    });

    syncNav();
  };

  restoreDraft();
  syncNav();

  form.addEventListener("input", () => {
    dirty = true;
    saveDraft();
  });
  form.addEventListener("change", () => {
    dirty = true;
    saveDraft();
  });

  window.addEventListener("beforeunload", (event) => {
    if (dirty) event.preventDefault();
  });

  prevBtn.addEventListener("click", () => {
    if (index > 0) show(index - 1);
  });

  nextBtn.addEventListener("click", async () => {
    if (!answered(cards[index])) {
      const skip = await window.BloomUi.confirm("You haven't answered this question. You can return to it before submitting.", {
        title: "Leave this question blank?",
        confirmLabel: "Continue without answering",
        variant: "assessment",
      });
      if (!skip) return;
    }
    if (index < cards.length - 1) show(index + 1);
  });

  let submitting = false;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitting) return;
    const missing = unansweredCount();
    if (missing) {
      const go = await window.BloomUi.confirm(
        missing === 1 ? "1 question is still empty. Submit anyway?" : `${missing} questions are still empty. Submit anyway?`,
        { title: "Submit with empty answers?", confirmLabel: "Submit anyway" }
      );
      if (!go) {
        return;
      }
    }
    const warning = form.getAttribute("data-confirm-submit");
    if (warning) {
      const confirmed = await window.BloomUi.confirm(warning, {
        title: "Submit assessment?",
        confirmLabel: "Submit",
      });
      if (!confirmed) return;
    }
    submitting = true;
    dirty = false;
    clearDraft();
    submitBtn.disabled = true;
    window.BloomUi.showLoading(form.getAttribute("data-loading") || "Submitting…");
    HTMLFormElement.prototype.submit.call(form);
  });
})();
