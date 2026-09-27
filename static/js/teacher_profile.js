(function () {
  "use strict";

  const displayInput = document.querySelector('[data-teacher-field="displayName"]');
  const availabilityInput = document.querySelector('[data-teacher-field="availabilityNote"]');
  const switches = document.querySelectorAll("[data-teacher-pref]");
  const requestBtn = document.querySelector("[data-teacher-request-change]");
  const requestDialog = document.getElementById("teacher-profile-request-dialog");
  const identityName = document.getElementById("profile-name");

  // TODO: persist this object to the backend (display name, availability, notification prefs).
  // Fields do not exist yet — in-memory only, resets on refresh.
  const state = {
    displayName: displayInput ? displayInput.value : "",
    availabilityNote: availabilityInput ? availabilityInput.value : "",
    notifications: {
      newStudentMessages: true,
      submissionsReady: true,
      weeklySummary: false,
    },
  };

  function readSwitchState() {
    switches.forEach((btn) => {
      const key = btn.getAttribute("data-teacher-pref");
      if (!key || !(key in state.notifications)) return;
      state.notifications[key] = btn.getAttribute("aria-checked") === "true";
    });
  }

  readSwitchState();

  if (displayInput) {
    displayInput.addEventListener("input", () => {
      state.displayName = displayInput.value;
      if (identityName) identityName.textContent = state.displayName;
      // TODO: debounce POST /profile { action: "display_name", display_name } once the field exists.
    });
  }

  if (availabilityInput) {
    availabilityInput.addEventListener("input", () => {
      state.availabilityNote = availabilityInput.value;
      // TODO: debounce POST /profile { action: "availability_note" } once a column exists.
    });
  }

  switches.forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-teacher-pref");
      const next = btn.getAttribute("aria-checked") !== "true";
      btn.setAttribute("aria-checked", next ? "true" : "false");
      if (key && key in state.notifications) state.notifications[key] = next;
      // TODO: persist notification prefs (newStudentMessages, submissionsReady, weeklySummary).
    });
  });

  function mailtoHref() {
    const email = (requestBtn && requestBtn.getAttribute("data-admin-email")) || "admin@letran-calamba.edu.ph";
    const subject = (requestBtn && requestBtn.getAttribute("data-subject")) || "";
    const section = (requestBtn && requestBtn.getAttribute("data-section")) || "";
    const mailSubject = encodeURIComponent("Teaching profile change request");
    const mailBody = encodeURIComponent(
      "I would like to request a change to my teaching assignment.\n\nCurrent subject: " +
        subject +
        "\nCurrent section: " +
        section +
        "\n\nRequested change:\n"
    );
    return "mailto:" + email + "?subject=" + mailSubject + "&body=" + mailBody;
  }

  if (requestBtn) {
    const mailLink = document.querySelector("[data-teacher-request-mailto]");
    if (mailLink) mailLink.setAttribute("href", mailtoHref());

    requestBtn.addEventListener("click", () => {
      // TODO: connect to a real admin request flow if one is added; mailto is a placeholder.
      if (requestDialog && typeof requestDialog.showModal === "function") {
        requestDialog.showModal();
        return;
      }
      window.location.href = mailtoHref();
    });
  }

  if (requestDialog) {
    const closeBtn = requestDialog.querySelector("[data-teacher-request-close]");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => requestDialog.close());
    }
    requestDialog.addEventListener("click", (event) => {
      if (event.target === requestDialog) requestDialog.close();
    });
  }
})();
