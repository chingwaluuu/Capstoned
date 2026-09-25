(() => {
  const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

  const withCsrf = (init = {}) => {
    const headers = new Headers(init.headers || {});
    const token = csrfToken();
    if (token && !headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", token);
    return { ...init, headers };
  };

  const ensureFormCsrf = (form) => {
    if (!form || (form.method || "get").toLowerCase() !== "post") return;
    let input = form.querySelector('input[name="csrf_token"]');
    if (!input) {
      input = document.createElement("input");
      input.type = "hidden";
      input.name = "csrf_token";
      form.appendChild(input);
    }
    input.value = csrfToken();
  };

  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      ensureFormCsrf(form);
    },
    true
  );

  const prefersReducedMotion = () =>
    window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
    document.documentElement.classList.contains("pref-reduce-motion");

  const overlay = (message, options = {}) => {
    let node = document.getElementById("qol-overlay");
    if (!node) {
      node = document.createElement("div");
      node.id = "qol-overlay";
      node.className = "qol-overlay";
      node.hidden = true;
      node.innerHTML = `<div class="qol-overlay-card" role="status" aria-live="assertive"><span class="qol-spinner" aria-hidden="true"></span><p class="qol-overlay-msg"></p></div>`;
      document.body.appendChild(node);
    }
    const pageNav = Boolean(options.pageNav);
    node.classList.toggle("is-page-nav", pageNav);
    const msg = node.querySelector(".qol-overlay-msg") || node.querySelector("p");
    msg.textContent = message || (pageNav ? "Loading page…" : "");
    node.hidden = false;
    if (prefersReducedMotion()) {
      node.classList.add("is-visible");
      return;
    }
    // Next frame so opacity can transition from 0 → 1.
    requestAnimationFrame(() => {
      node.classList.add("is-visible");
    });
  };

  const hideOverlay = () => {
    const node = document.getElementById("qol-overlay");
    if (!node) return;
    if (prefersReducedMotion() || !node.classList.contains("is-visible")) {
      node.classList.remove("is-visible", "is-page-nav");
      node.hidden = true;
      return;
    }
    const finish = (event) => {
      if (event && event.target !== node) return;
      node.removeEventListener("transitionend", finish);
      if (!node.classList.contains("is-visible")) {
        node.classList.remove("is-page-nav");
        node.hidden = true;
      }
    };
    node.addEventListener("transitionend", finish);
    node.classList.remove("is-visible");
  };

  const shouldShowPageLoading = (anchor, event) => {
    if (!(anchor instanceof HTMLAnchorElement)) return false;
    if (event.defaultPrevented) return false;
    if (event.button !== 0) return false;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    if (anchor.hasAttribute("download")) return false;
    if (anchor.dataset.noLoading != null) return false;
    if (anchor.getAttribute("aria-disabled") === "true") return false;
    const target = (anchor.getAttribute("target") || "").toLowerCase();
    if (target && target !== "_self") return false;
    const href = anchor.getAttribute("href");
    if (!href || href.startsWith("#") || href.startsWith("javascript:")) return false;
    let url;
    try {
      url = new URL(anchor.href, window.location.href);
    } catch {
      return false;
    }
    if (url.origin !== window.location.origin) return false;
    if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) {
      return false;
    }
    return true;
  };

  document.addEventListener(
    "click",
    (event) => {
      const anchor = event.target.closest?.("a[href]");
      if (!shouldShowPageLoading(anchor, event)) return;
      overlay("Loading page…", { pageNav: true });
    },
    true
  );

  const confirmAction = (message, options = {}) =>
    new Promise((resolve) => {
      let dialog = document.getElementById("bloom-confirm-dialog");
      if (!dialog) {
        dialog = document.createElement("dialog");
        dialog.id = "bloom-confirm-dialog";
        dialog.className = "bloom-dialog";
        dialog.innerHTML =
          '<div class="bloom-dialog-card" role="document">' +
          '<h2 class="bloom-dialog-title">Please confirm</h2>' +
          '<p class="bloom-dialog-message"></p>' +
          '<div class="bloom-dialog-actions">' +
          '<button type="button" class="today-action today-action-soft" data-dialog-cancel>Cancel</button>' +
          '<button type="button" class="btn-primary btn-inline" data-dialog-confirm>Continue</button>' +
          "</div></div>";
        document.body.appendChild(dialog);
      }

      const messageNode = dialog.querySelector(".bloom-dialog-message");
      const titleNode = dialog.querySelector(".bloom-dialog-title");
      const cancel = dialog.querySelector("[data-dialog-cancel]");
      const confirm = dialog.querySelector("[data-dialog-confirm]");
      const previousFocus = document.activeElement;
      messageNode.textContent = message;
      titleNode.textContent = options.title || "Please confirm";
      confirm.textContent = options.confirmLabel || "Continue";

      let finished = false;
      const finish = (accepted) => {
        if (finished) return;
        finished = true;
        dialog.close();
        if (previousFocus instanceof HTMLElement) previousFocus.focus();
        resolve(accepted);
      };

      cancel.onclick = () => finish(false);
      confirm.onclick = () => finish(true);
      dialog.oncancel = (event) => {
        event.preventDefault();
        finish(false);
      };
      dialog.onclick = (event) => {
        if (event.target === dialog) finish(false);
      };
      dialog.showModal();
      cancel.focus();
    });

  const popovers = [
    ["profile-toggle", "profile-panel"],
    ["settings-toggle", "settings-panel"],
  ]
    .map(([toggleId, panelId]) => ({
      toggle: document.getElementById(toggleId),
      panel: document.getElementById(panelId),
    }))
    .filter((item) => item.toggle && item.panel);

  const closePopover = (item) => {
    item.panel.hidden = true;
    item.panel.classList.remove("is-open");
    item.toggle.setAttribute("aria-expanded", "false");
  };

  const closeAllPopovers = () => popovers.forEach(closePopover);

  const openPopover = (item) => {
    closeAllPopovers();
    closeNotifyDropdown();
    item.panel.hidden = false;
    item.panel.classList.add("is-open");
    item.toggle.setAttribute("aria-expanded", "true");
  };

  // Announcement bell dropdown — independent of sidebar (pro-shell.js) and of the
  // generic profile/settings popover list (do not put notify back in that array).
  const notifyToggle = document.getElementById("notify-toggle");
  const notifyDropdown = document.getElementById("notify-dropdown");

  const closeMobileSidebarIfOpen = () => {
    const body = document.body;
    if (!body.classList.contains("pro-sidebar-open")) return;
    body.classList.remove("pro-sidebar-open", "pro-scroll-locked");
    const backdrop = document.getElementById("pro-sidebar-backdrop");
    if (backdrop) backdrop.hidden = true;
    const sidebarToggle = document.getElementById("sidebar-toggle");
    if (sidebarToggle) sidebarToggle.setAttribute("aria-expanded", "false");
  };

  const closeNotifyDropdown = () => {
    if (!notifyToggle || !notifyDropdown) return;
    notifyDropdown.classList.remove("is-open");
    notifyToggle.setAttribute("aria-expanded", "false");
    if (prefersReducedMotion()) {
      notifyDropdown.hidden = true;
      return;
    }
    const finish = (event) => {
      if (event && event.target !== notifyDropdown) return;
      notifyDropdown.removeEventListener("transitionend", finish);
      if (!notifyDropdown.classList.contains("is-open")) notifyDropdown.hidden = true;
    };
    notifyDropdown.addEventListener("transitionend", finish);
    // Fallback if transitionend doesn't fire (display/hidden edge cases).
    window.setTimeout(() => {
      if (!notifyDropdown.classList.contains("is-open")) notifyDropdown.hidden = true;
    }, 280);
  };

  const openNotifyDropdown = () => {
    if (!notifyToggle || !notifyDropdown) return;
    closeAllPopovers();
    closeMobileSidebarIfOpen();
    notifyDropdown.hidden = false;
    notifyToggle.setAttribute("aria-expanded", "true");
    if (prefersReducedMotion()) {
      notifyDropdown.classList.add("is-open");
      return;
    }
    requestAnimationFrame(() => notifyDropdown.classList.add("is-open"));
  };

  const toggleNotifyDropdown = () => {
    if (!notifyDropdown) return;
    if (notifyToggle.getAttribute("aria-expanded") === "true") closeNotifyDropdown();
    else openNotifyDropdown();
  };

  if (notifyToggle && notifyDropdown) {
    notifyToggle.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      toggleNotifyDropdown();
    });
  }

  popovers.forEach((item) => {
    item.toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      if (item.panel.hidden) openPopover(item);
      else closePopover(item);
    });
  });

  document.addEventListener("click", (event) => {
    popovers.forEach((item) => {
      if (item.panel.hidden) return;
      if (!item.panel.contains(event.target) && !item.toggle.contains(event.target)) {
        closePopover(item);
      }
    });
    if (
      notifyDropdown &&
      notifyToggle &&
      notifyToggle.getAttribute("aria-expanded") === "true" &&
      !notifyDropdown.contains(event.target) &&
      !notifyToggle.contains(event.target)
    ) {
      closeNotifyDropdown();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeAllPopovers();
    if (notifyToggle?.getAttribute("aria-expanded") === "true") closeNotifyDropdown();
  });

  const prefKey = (name) => `bloom-pref-${name}`;
  const applyPref = (name, on) => {
    const root = document.documentElement;
    if (name === "large-type") root.classList.toggle("pref-large-type", on);
    if (name === "reduce-motion") root.classList.toggle("pref-reduce-motion", on);
    if (name === "notify-badge") root.classList.toggle("pref-hide-badge", !on);
  };

  document.querySelectorAll("[data-pref]").forEach((input) => {
    const name = input.getAttribute("data-pref");
    const stored = localStorage.getItem(prefKey(name));
    const on = name === "notify-badge" ? stored !== "0" : stored === "1";
    input.checked = on;
    applyPref(name, on);
    input.addEventListener("change", () => {
      localStorage.setItem(prefKey(name), input.checked ? "1" : "0");
      applyPref(name, input.checked);
    });
  });

  document.querySelectorAll('input[type="password"]').forEach((input) => {
    if (input.closest(".password-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = "password-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "password-toggle";
    button.setAttribute("aria-label", "Show password");
    button.textContent = "Show";
    wrap.appendChild(button);
    button.addEventListener("click", () => {
      const hidden = input.type === "password";
      input.type = hidden ? "text" : "password";
      button.textContent = hidden ? "Hide" : "Show";
      button.setAttribute("aria-label", hidden ? "Hide password" : "Show password");
    });
  });

  document.querySelectorAll('input[type="file"]').forEach((input) => {
    const hint = document.createElement("p");
    hint.className = "file-chosen";
    input.insertAdjacentElement("afterend", hint);
    const update = () => {
      hint.textContent = input.files && input.files[0] ? input.files[0].name : "";
    };
    input.addEventListener("change", update);
    update();
  });

  document.querySelectorAll("[data-fill-login]").forEach((button) => {
    button.addEventListener("click", () => {
      const [email, password] = (button.getAttribute("data-fill-login") || "").split("|");
      const emailInput = document.getElementById("email");
      const passwordInput = document.getElementById("password");
      if (emailInput) emailInput.value = email || "";
      if (passwordInput) passwordInput.value = password || "";
      emailInput?.focus();
    });
  });

  document.querySelectorAll("[data-fill-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = document.getElementById(button.getAttribute("data-fill-target"));
      if (target) target.value = button.getAttribute("data-fill-value") || "";
    });
  });

  const emailInput = document.getElementById("email");
  if (emailInput && emailInput.form && emailInput.form.getAttribute("action")?.includes("login")) {
    const saved = localStorage.getItem("bloom-email");
    if (saved && !emailInput.value) emailInput.value = saved;
    emailInput.form.addEventListener("submit", () => {
      localStorage.setItem("bloom-email", emailInput.value.trim());
    });
  }

  const setFieldError = (input, message) => {
    if (!input) return;
    const id = `${input.id || input.name}-error`;
    let err = document.getElementById(id);
    if (!err) {
      err = document.createElement("p");
      err.className = "field-error";
      err.id = id;
      input.insertAdjacentElement("afterend", err);
    }
    if (message) {
      err.hidden = false;
      err.textContent = message;
      input.setAttribute("aria-invalid", "true");
      input.setAttribute("aria-describedby", id);
    } else {
      err.hidden = true;
      err.textContent = "";
      input.removeAttribute("aria-invalid");
    }
  };

  const setChoiceError = (form, fields, message) => {
    if (!fields.length) return;
    const fieldset = fields[0].closest("fieldset");
    let err = form.querySelector("#question-types-error");
    if (!err) {
      err = document.createElement("p");
      err.className = "field-error";
      err.id = `choice-error-${Math.random().toString(36).slice(2)}`;
      err.setAttribute("role", "alert");
      fieldset?.appendChild(err);
    }
    err.hidden = !message;
    err.textContent = message || "";
    fieldset?.setAttribute("aria-invalid", message ? "true" : "false");
    if (message) fieldset?.setAttribute("aria-describedby", err.id);
    else fieldset?.removeAttribute("aria-describedby");
  };

  document.querySelectorAll("[data-match]").forEach((input) => {
    const sync = () => {
      const other = document.querySelector(input.getAttribute("data-match"));
      if (!other) return;
      const mismatch = input.value && other.value && input.value !== other.value;
      setFieldError(input, mismatch ? input.getAttribute("data-match-message") || "Values must match." : "");
    };
    input.addEventListener("input", sync);
    const other = document.querySelector(input.getAttribute("data-match"));
    other?.addEventListener("input", sync);
  });

  document.querySelectorAll(".flash-dismiss").forEach((button) => {
    button.addEventListener("click", () => {
      button.closest(".flash")?.remove();
    });
  });

  document.querySelectorAll(".flash-success").forEach((flash) => {
    window.setTimeout(() => {
      flash.classList.add("is-fading");
      window.setTimeout(() => flash.remove(), 320);
    }, 5200);
  });

  let offlineBar = null;
  const setOnlineState = () => {
    if (navigator.onLine) {
      offlineBar?.remove();
      offlineBar = null;
      return;
    }
    if (offlineBar) return;
    offlineBar = document.createElement("div");
    offlineBar.className = "offline-bar";
    offlineBar.setAttribute("role", "alert");
    offlineBar.textContent = "You’re offline. Changes may not save until you’re back online.";
    document.body.prepend(offlineBar);
  };
  window.addEventListener("online", setOnlineState);
  window.addEventListener("offline", setOnlineState);
  setOnlineState();

  const expiresAt = Number(document.body.getAttribute("data-session-expires") || 0);
  if (expiresAt > 0) {
    const warnAt = expiresAt * 1000 - 5 * 60 * 1000;
    const delay = warnAt - Date.now();
    if (delay > 0) {
      window.setTimeout(() => {
        if (document.getElementById("session-expiry-banner")) return;
        const banner = document.createElement("div");
        banner.id = "session-expiry-banner";
        banner.className = "session-expiry-banner";
        banner.setAttribute("role", "status");
        banner.innerHTML =
          '<span>Your signed-in session ends in about 5 minutes. Save your work, or sign in again soon.</span>' +
          `<a href="${document.body.getAttribute("data-login-url") || "/login"}">Sign in again</a>`;
        document.body.prepend(banner);
      }, delay);
    }
  }

  document.querySelectorAll("form").forEach((form) => {
    if (form.id === "practice-take-form" || form.id === "chat-form" || form.id === "announce-mark-all") return;
    const typeFields = [...form.querySelectorAll('input[name="types"]')];
    typeFields.forEach((field) => {
      field.addEventListener("change", () => {
        if (typeFields.some((box) => box.checked)) setChoiceError(form, typeFields, "");
      });
    });

    form.addEventListener("submit", async (event) => {
      if (form.dataset.confirm && form.dataset.confirmedOnce !== "1") {
        event.preventDefault();
        const accepted = await confirmAction(form.dataset.confirm, {
          confirmLabel: form.dataset.confirmLabel || "Continue",
        });
        if (accepted) {
          form.dataset.confirmedOnce = "1";
          form.requestSubmit(event.submitter || undefined);
        }
        return;
      }
      delete form.dataset.confirmedOnce;
      if (typeFields.length && !typeFields.some((box) => box.checked)) {
        event.preventDefault();
        setChoiceError(form, typeFields, "Choose at least one question type.");
        typeFields[0].focus();
        return;
      }
      const matchInput = form.querySelector("[data-match]");
      if (matchInput) {
        const other = document.querySelector(matchInput.getAttribute("data-match"));
        if (other && matchInput.value !== other.value) {
          event.preventDefault();
          setFieldError(matchInput, matchInput.getAttribute("data-match-message") || "Values must match.");
          matchInput.focus();
          return;
        }
      }
      const submit = form.querySelector('button[type="submit"]:not([hidden])');
      if (submit) submit.disabled = true;
      const loading = form.dataset.loading || (form.dataset.confirm ? "Saving changes…" : "");
      if (loading) overlay(loading);
    });
  });

  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    hideOverlay();
    document.querySelectorAll('button[type="submit"]').forEach((button) => {
      button.disabled = false;
    });
  });

  // Soften silent kick: if a fetch gets 401 on authenticated pages, send users to login with context.
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const nextInit = withCsrf(init || {});
    // Also stamp FormData bodies that omit csrf_token.
    if (nextInit.body instanceof FormData && csrfToken() && !nextInit.body.has("csrf_token")) {
      nextInit.body.set("csrf_token", csrfToken());
    }
    const response = await originalFetch(input, nextInit);
    if (response.status === 401 && document.body?.dataset.loginUrl) {
      window.location.assign(document.body.getAttribute("data-login-url") || "/login");
    }
    return response;
  };

  window.BloomCsrf = { token: csrfToken, withCsrf, ensureFormCsrf };
  window.BloomUi = {
    confirm: confirmAction,
    hideLoading: hideOverlay,
    setFieldError,
    showLoading: overlay,
  };
})();
