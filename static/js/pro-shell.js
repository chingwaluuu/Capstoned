window.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("sidebar-toggle");
  const sidebar = document.getElementById("pro-sidebar");
  const backdrop = document.getElementById("pro-sidebar-backdrop");
  const body = document.body;
  if (!toggle || !sidebar || !backdrop) return;

  const key = "bloom-pro-sidebar";
  const mobile = window.matchMedia("(max-width: 860px)");
  const focusMode = body.classList.contains("pro-focus");
  let returnFocus = null;

  toggle.setAttribute("aria-controls", sidebar.id);

  const setSidebarInert = (inert) => {
    if ("inert" in sidebar) sidebar.inert = inert;
    else if (inert) sidebar.setAttribute("inert", "");
    else sidebar.removeAttribute("inert");
  };

  const sync = () => {
    const isMobile = mobile.matches;
    const isOpen = isMobile
      ? body.classList.contains("pro-sidebar-open")
      : !body.classList.contains("pro-sidebar-collapsed");

    toggle.setAttribute("aria-expanded", String(isOpen));
    if (isMobile) {
      toggle.setAttribute("aria-label", isOpen ? "Close navigation" : "Open navigation");
    } else {
      toggle.setAttribute("aria-label", isOpen ? "Hide navigation" : "Show navigation");
    }
    backdrop.hidden = !isMobile || !isOpen;
    body.classList.toggle("pro-scroll-locked", isMobile && isOpen);
    setSidebarInert(isMobile && !isOpen);
  };

  const closeMobile = ({ restoreFocus = true } = {}) => {
    body.classList.remove("pro-sidebar-open");
    sync();
    if (restoreFocus && returnFocus instanceof HTMLElement) returnFocus.focus();
    returnFocus = null;
  };

  const openMobile = () => {
    returnFocus = document.activeElement;
    body.classList.add("pro-sidebar-open");
    sync();
    const firstLink = sidebar.querySelector(".pro-nav-link");
    if (firstLink instanceof HTMLElement) firstLink.focus();
  };

  if (mobile.matches) {
    body.classList.remove("pro-sidebar-open");
  } else if (focusMode || localStorage.getItem(key) === "1") {
    body.classList.add("pro-sidebar-collapsed");
  }
  sync();

  toggle.addEventListener("click", () => {
    if (mobile.matches) {
      if (body.classList.contains("pro-sidebar-open")) closeMobile();
      else openMobile();
      return;
    }
    body.classList.toggle("pro-sidebar-collapsed");
    if (!focusMode) {
      localStorage.setItem(key, body.classList.contains("pro-sidebar-collapsed") ? "1" : "0");
    }
    sync();
  });

  backdrop.addEventListener("click", () => closeMobile());
  sidebar.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      if (mobile.matches) closeMobile({ restoreFocus: false });
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && mobile.matches && body.classList.contains("pro-sidebar-open")) {
      event.preventDefault();
      closeMobile();
    }
  });

  mobile.addEventListener("change", () => {
    body.classList.remove("pro-sidebar-open");
    if (!mobile.matches && !focusMode) {
      body.classList.toggle("pro-sidebar-collapsed", localStorage.getItem(key) === "1");
    }
    sync();
  });
});
