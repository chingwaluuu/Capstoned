(() => {
  const steppers = document.querySelectorAll("[data-count-stepper]");
  const clamp = (value, min, max) => {
    const n = Number.parseInt(String(value), 10);
    if (!Number.isFinite(n)) return min;
    return Math.min(max, Math.max(min, n));
  };

  steppers.forEach((root) => {
    const input = root.querySelector(".count-stepper-input");
    if (!(input instanceof HTMLInputElement)) return;

    const min = Number.parseInt(root.getAttribute("data-min") || input.min || "1", 10) || 1;
    const max = Number.parseInt(root.getAttribute("data-max") || input.max || "15", 10) || 15;

    const setValue = (next) => {
      input.value = String(clamp(next, min, max));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    };

    setValue(input.value);

    root.querySelectorAll("[data-count-step]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const delta = Number.parseInt(btn.getAttribute("data-count-step") || "0", 10) || 0;
        setValue((Number.parseInt(input.value, 10) || min) + delta);
        input.focus({ preventScroll: true });
      });
    });

    input.addEventListener("blur", () => setValue(input.value));
    input.addEventListener("change", () => {
      input.value = String(clamp(input.value, min, max));
    });
  });

  const form = document.querySelector("[data-practice-setup]");
  if (!(form instanceof HTMLFormElement)) return;

  const focusLabels = {
    mixed: "Mixed skills",
    c4: "Analyze",
    c5: "Evaluate",
    c6: "Create",
  };

  const summaryLine = form.querySelector("[data-setup-summary-line]");
  const submit = form.querySelector("[data-setup-submit]");
  const readyHint = form.querySelector("[data-setup-ready-hint]");
  const subjectMeta = form.closest(".practice-setup")?.querySelector(".practice-setup-meta");
  const materialTitle = form.closest(".practice-setup")?.querySelector(".practice-setup-material");

  const selectedRadioLabel = (name) => {
    const checked = form.querySelector(`input[name="${name}"]:checked`);
    if (!(checked instanceof HTMLInputElement)) return "";
    if (name === "focus") return focusLabels[checked.value] || checked.value;
    const title = checked.closest("label")?.querySelector(".practice-option-title");
    return title?.textContent?.trim() || checked.value;
  };

  const syncSelectedClasses = () => {
    form.querySelectorAll(".practice-option, .practice-type").forEach((label) => {
      const input = label.querySelector("input");
      label.classList.toggle("is-selected", Boolean(input?.checked));
    });
  };

  const syncSummary = () => {
    if (!(summaryLine instanceof HTMLElement)) return;
    const subject = subjectMeta?.textContent?.split("·")[0]?.trim() || "";
    const material = materialTitle?.textContent?.trim() || "";
    const difficulty = selectedRadioLabel("difficulty");
    const focus = selectedRadioLabel("focus");
    const countInput = form.querySelector("#count");
    const count = clamp(
      countInput instanceof HTMLInputElement ? countInput.value : "1",
      1,
      15
    );
    const questionWord = count === 1 ? "question" : "questions";
    summaryLine.textContent = [subject, material, difficulty, focus, `${count} ${questionWord}`]
      .filter(Boolean)
      .join(" · ");
  };

  const syncSubmitState = () => {
    const typeFields = [...form.querySelectorAll('input[name="types"]')];
    const hasType = typeFields.some((box) => box instanceof HTMLInputElement && box.checked);
    if (submit instanceof HTMLButtonElement) {
      submit.disabled = !hasType;
    }
    if (readyHint instanceof HTMLElement) {
      readyHint.hidden = hasType;
    }
  };

  const syncAll = () => {
    syncSelectedClasses();
    syncSummary();
    syncSubmitState();
  };

  form.addEventListener("change", syncAll);
  form.addEventListener("input", syncAll);
  syncAll();
})();
