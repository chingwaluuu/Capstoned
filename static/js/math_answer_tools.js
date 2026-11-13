(() => {
  "use strict";

  document.querySelectorAll("[data-math-answer]").forEach((panel) => {
    const input = panel.querySelector(".math-answer-input");
    const preview = panel.querySelector("[data-math-preview]");
    const previewText = panel.querySelector("[data-math-preview-text]");
    if (!input || !preview || !previewText) return;

    const syncPreview = () => {
      const value = input.value;
      previewText.textContent = value;
      preview.hidden = !value.trim();
    };

    panel.querySelectorAll("[data-math-symbol]").forEach((button) => {
      button.addEventListener("click", () => {
        const symbol = button.getAttribute("data-math-symbol") || "";
        const start = input.selectionStart ?? input.value.length;
        const end = input.selectionEnd ?? start;
        input.setRangeText(symbol, start, end, "end");
        input.focus();
        input.dispatchEvent(new Event("input", { bubbles: true }));
        syncPreview();
      });
    });

    input.addEventListener("input", syncPreview);
    syncPreview();
  });
})();
