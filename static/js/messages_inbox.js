(() => {
  const list = document.querySelector("[data-message-list]");
  if (!list) return;

  const rows = [...list.querySelectorAll(".message-row")];
  const empty = document.querySelector("[data-message-empty]");
  const emptyTitle = empty ? empty.querySelector("[data-message-empty-title]") : null;
  const emptyCopy = empty ? empty.querySelector("[data-message-empty-copy]") : null;
  const countBadge = document.querySelector("[data-message-count]");
  const searchInput = document.querySelector("[data-message-search] input");
  const filterRow = document.querySelector("[data-message-filters]");
  const pills = filterRow ? [...filterRow.querySelectorAll("[data-message-filter]")] : [];

  const SUBJECT_LABELS = {
    science: "Science",
    english: "English",
    mathematics: "Math",
  };

  let activeFilter = "all";
  let query = "";

  const emptyCopyFor = (filter) => {
    if (query) {
      return {
        title: "No conversations found",
        copy: "Try a different search or filter.",
      };
    }
    if (filter === "unread") {
      return {
        title: "No unread messages",
        copy: "You’re all caught up. New teacher replies will show up here.",
      };
    }
    if (SUBJECT_LABELS[filter]) {
      return {
        title: `No ${SUBJECT_LABELS[filter]} conversations yet`,
        copy: `When you message your ${SUBJECT_LABELS[filter]} teacher, the thread will appear here.`,
      };
    }
    return {
      title: "No conversations found",
      copy: "Try a different search or filter.",
    };
  };

  const updateCount = (visible) => {
    if (!countBadge) return;
    const label = visible === 1 ? "1 conversation" : `${visible} conversations`;
    countBadge.textContent = label;
    countBadge.classList.toggle("is-muted", visible === 0);
  };

  const apply = () => {
    let visible = 0;
    rows.forEach((row) => {
      const subject = row.getAttribute("data-subject") || "";
      const unread = row.getAttribute("data-unread") === "1";
      const hay = (row.getAttribute("data-search") || "").toLowerCase();
      const filterOk =
        activeFilter === "all" ||
        (activeFilter === "unread" && unread) ||
        (activeFilter !== "all" && activeFilter !== "unread" && subject === activeFilter);
      const searchOk = !query || hay.includes(query);
      const show = filterOk && searchOk;
      row.classList.toggle("is-filtered-out", !show);
      row.hidden = !show;
      row.setAttribute("aria-hidden", show ? "false" : "true");
      if (show) visible += 1;
    });

    updateCount(visible);

    if (empty) {
      const showEmpty = visible === 0;
      const wasHidden = empty.hidden;
      empty.hidden = !showEmpty;
      empty.classList.toggle("is-filtered-out", !showEmpty);
      if (showEmpty) {
        const copy = emptyCopyFor(activeFilter);
        if (emptyTitle) emptyTitle.textContent = copy.title;
        if (emptyCopy) emptyCopy.textContent = copy.copy;
        // Re-trigger entrance when the filter empty state becomes visible again.
        if (wasHidden) {
          empty.classList.remove("pro-toast-in");
          void empty.offsetWidth;
          empty.classList.add("pro-toast-in");
        }
      }
    }
  };

  const setFilter = (filter) => {
    activeFilter = filter || "all";
    pills.forEach((item) => {
      const on = (item.getAttribute("data-message-filter") || "") === activeFilter;
      item.classList.toggle("active", on);
      item.classList.toggle("is-active", on);
      item.setAttribute("aria-pressed", on ? "true" : "false");
    });
    apply();
  };

  if (filterRow) {
    filterRow.addEventListener("click", (event) => {
      const pill = event.target.closest("[data-message-filter]");
      if (!pill || !filterRow.contains(pill)) return;
      event.preventDefault();
      setFilter(pill.getAttribute("data-message-filter") || "all");
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      query = searchInput.value.trim().toLowerCase();
      apply();
    });
  }

  // Initialize aria-pressed + count from the default "All" state.
  setFilter("all");

  // Freeze list stagger after first entrance so filter show/hide does not replay it
  // (rows use display:none when filtered, which would restart CSS animations).
  window.setTimeout(() => {
    list.classList.add("is-stagger-done");
  }, 650);
})();
