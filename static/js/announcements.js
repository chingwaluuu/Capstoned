(() => {
  const page = document.querySelector(".announce-page");
  if (!page) return;

  const layout = document.querySelector(".announce-layout");
  const listPane = document.querySelector(".announce-list-pane");
  const detailPane = document.querySelector(".announce-detail-pane");
  const items = () => [...document.querySelectorAll(".announce-item")];
  const groups = [...document.querySelectorAll(".announce-group")];
  const input = document.getElementById("announce-q");
  const searchEmpty = document.getElementById("announce-search-empty");
  const filterEmpty = document.getElementById("announce-filter-empty");
  const detail = document.getElementById("announce-detail");
  const empty = document.getElementById("announce-detail-empty");
  const skeleton = document.getElementById("announce-skeleton");
  const loadError = document.getElementById("announce-load-error");
  const retryButton = document.getElementById("announce-retry");
  const fallbackLink = document.getElementById("announce-fallback");
  const back = document.getElementById("announce-back");
  const markAllForm = document.getElementById("announce-mark-all");
  const selectedInput = document.getElementById("announce-selected-id");
  const unreadChip = document.getElementById("announce-chip-unread");
  const kicker = document.getElementById("announce-detail-kicker");
  const title = document.getElementById("announce-detail-title");
  const byline = document.getElementById("announce-detail-by");
  const dateEl = document.getElementById("announce-detail-date");
  const bodyEl = document.getElementById("announce-detail-body");

  const desktopQuery = window.matchMedia("(min-width: 840px)");
  const isDesktop = () => desktopQuery.matches;
  const currentFilter = () => page.getAttribute("data-filter") || "all";
  const listHref = () => page.getAttribute("data-list-href") || back?.getAttribute("href") || "/announcements";
  const listIsVisible = () => Boolean(listPane && listPane.getClientRects().length);
  const visibleItems = () => items().filter((item) => !item.hidden);

  let inflight = null;
  let skeletonTimer = 0;
  let retryState = null;

  const itemById = (id) => document.querySelector(`.announce-item[data-id="${id}"]`);
  const selectedItem = () => document.querySelector(".announce-item.is-selected");

  const setHidden = (node, hidden) => {
    if (node) node.hidden = Boolean(hidden);
  };

  const setUnreadCount = (count) => {
    const safe = Math.max(0, Number(count) || 0);
    const navCount = document.getElementById("nav-announcements-count");
    if (navCount) {
      if (safe > 0) navCount.textContent = String(safe);
      else navCount.remove();
    }
    const toggle = document.getElementById("notify-toggle");
    if (toggle) {
      let dot = toggle.querySelector(".bell-dot");
      if (safe > 0) {
        if (!dot) {
          dot = document.createElement("span");
          dot.className = "bell-dot";
          toggle.appendChild(dot);
        }
        dot.textContent = String(safe);
      } else if (dot) {
        dot.remove();
      }
    }

    const notifyCount = document.querySelector(".notify-count");
    if (notifyCount) {
      notifyCount.classList.toggle("notify-count-quiet", safe === 0);
      notifyCount.textContent = safe > 0 ? `${safe} unread` : "All caught up";
    }

    if (unreadChip) {
      unreadChip.dataset.count = String(safe);
      unreadChip.textContent = safe > 0 ? `Unread · ${safe}` : "Unread";
    }

    if (markAllForm) setHidden(markAllForm, safe === 0);
  };

  const markItemReadOnServer = async (id) => {
    if (!id) return null;
    try {
      const payload = new FormData();
      const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
      if (token) payload.set("csrf_token", token);
      const response = await fetch(`/announcements/${id}/read`, {
        method: "POST",
        headers: {
          "X-Requested-With": "fetch",
          Accept: "application/json",
          ...(token ? { "X-CSRF-Token": token } : {}),
        },
        body: payload,
      });
      const data = await response.json();
      if (!response.ok || !data.ok) return null;
      return data;
    } catch (_error) {
      return null;
    }
  };

  const markNotifyRead = (id, all = false) => {
    document.querySelectorAll(".notify-item").forEach((row) => {
      if (!all && String(row.dataset.id) !== String(id)) return;
      row.classList.remove("is-unread");
      const marker = row.querySelector(".notify-new");
      if (marker) marker.hidden = true;
    });
  };

  const markItemRead = (item) => {
    if (!item) return;
    item.classList.remove("is-unread");
    item.querySelector(".unread-dot")?.classList.remove("is-on");
    const badge = item.querySelector(".announce-new");
    if (badge) badge.hidden = true;
    item.querySelector(".announce-unread-label")?.remove();
  };

  const hideReadFromUnreadFilter = (item) => {
    if (!item || currentFilter() !== "unread" || item.classList.contains("is-selected") || item.classList.contains("is-unread")) {
      return;
    }
    item.hidden = true;
    item.dataset.caught = "1";
  };

  const refreshGroups = () => {
    groups.forEach((group) => {
      const shown = [...group.querySelectorAll(".announce-item")].some((row) => !row.hidden);
      group.hidden = !shown;
    });
    const anyVisible = items().some((row) => !row.hidden);
    const searching = Boolean(input?.value.trim());
    if (searchEmpty) searchEmpty.hidden = anyVisible || !searching;
    if (filterEmpty) filterEmpty.hidden = anyVisible || searching || currentFilter() !== "unread";
    setHidden(detailPane, !anyVisible);
  };

  const setSelected = (item) => {
    const previous = selectedItem();
    items().forEach((row) => {
      const on = row === item;
      row.classList.toggle("is-selected", on);
      if (on) row.setAttribute("aria-current", "page");
      else row.removeAttribute("aria-current");
    });
    if (previous && previous !== item) hideReadFromUnreadFilter(previous);
    if (selectedInput) selectedInput.value = item ? item.dataset.id || "" : "";
    refreshGroups();
  };

  const showSkeleton = (show) => {
    window.clearTimeout(skeletonTimer);
    setHidden(skeleton, !show);
    if (show) {
      setHidden(detail, true);
      setHidden(empty, true);
    }
  };

  const showLoadError = (href, id) => {
    showSkeleton(false);
    setHidden(detail, true);
    setHidden(empty, true);
    setHidden(loadError, false);
    retryState = { href, id };
    if (fallbackLink) fallbackLink.href = href;
    retryButton?.focus();
  };

  const fillBody = (blocks) => {
    if (!bodyEl) return;
    bodyEl.replaceChildren();
    if (!blocks || !blocks.length) {
      const p = document.createElement("p");
      p.textContent = "No additional details were included with this announcement.";
      bodyEl.appendChild(p);
      return;
    }
    blocks.forEach((para) => {
      const p = document.createElement("p");
      (para || []).forEach((line, index) => {
        if (index) p.appendChild(document.createElement("br"));
        p.appendChild(document.createTextNode(line));
      });
      bodyEl.appendChild(p);
    });
  };

  const renderDetail = (payload) => {
    if (!detail || !payload) return;
    detail.dataset.announceId = String(payload.id);
    if (kicker) kicker.textContent = payload.subject || "";
    if (title) title.textContent = payload.title || "";
    if (byline) byline.textContent = payload.teacher ? `Posted by ${payload.teacher}` : "";
    if (dateEl) {
      dateEl.textContent = payload.posted || "";
      dateEl.title = payload.posted || "";
    }
    fillBody(payload.body_blocks);
    document.title = `${payload.title} — Announcements — Bloom`;
    detail.classList.remove("is-enter");
    void detail.offsetWidth;
    detail.classList.add("is-enter");
  };

  const openLayout = (open) => {
    layout?.classList.toggle("is-open", Boolean(open));
    setHidden(back, !open);
    setHidden(empty, open);
    if (!open) {
      showSkeleton(false);
      setHidden(loadError, true);
      retryState = null;
      setHidden(detail, true);
      document.title = "Announcements — Bloom";
    }
  };

  const applyReadFromServer = (id, unreadCount) => {
    const item = itemById(id);
    if (item) {
      item.classList.add("is-selected");
      markItemRead(item);
    }
    markNotifyRead(id);
    setUnreadCount(unreadCount);
  };

  const loadAnnouncement = async (href, { history = "push", id = null } = {}) => {
    const url = new URL(href, window.location.origin);
    url.searchParams.delete("arrive");
    const announceId = id || url.pathname.split("/").pop();
    const item = itemById(announceId);
    if (item) setSelected(item);
    openLayout(true);
    setHidden(empty, true);
    setHidden(back, false);
    setHidden(loadError, true);

    if (detail && !detail.hidden && detail.dataset.announceId === String(announceId)) {
      if (history === "push") window.history.pushState({ announceId }, "", url.pathname + url.search);
      return;
    }

    if (inflight) inflight.abort();
    inflight = new AbortController();
    const { signal } = inflight;
    window.clearTimeout(skeletonTimer);
    skeletonTimer = window.setTimeout(
      () => {
        if (!signal.aborted) showSkeleton(true);
      },
      detail && !detail.hidden ? 160 : 0
    );

    try {
      const response = await fetch(url.pathname + url.search, {
        headers: { "X-Requested-With": "fetch", Accept: "application/json" },
        cache: "no-store",
        signal,
      });
      const data = await response.json();
      if (!response.ok || !data.ok || !data.selected) {
        showLoadError(url.pathname + url.search, announceId);
        return;
      }
      showSkeleton(false);
      setHidden(loadError, true);
      retryState = null;
      setHidden(detail, false);
      renderDetail(data.selected);
      const marked = await markItemReadOnServer(data.selected.id);
      applyReadFromServer(data.selected.id, marked?.unread_announcements ?? data.unread_announcements);
      if (data.list_href) {
        page.setAttribute("data-list-href", data.list_href);
        if (back) back.setAttribute("href", data.list_href);
      }
      if (history === "push") window.history.pushState({ announceId: data.selected.id }, "", url.pathname + url.search);
      else if (history === "replace") window.history.replaceState({ announceId: data.selected.id }, "", url.pathname + url.search);
      item?.scrollIntoView({ block: "nearest", behavior: "auto" });
    } catch (error) {
      if (error.name === "AbortError") return;
      showLoadError(url.pathname + url.search, announceId);
    }
  };

  const closeDetail = ({ history = "push" } = {}) => {
    const current = selectedItem();
    if (current) {
      current.classList.remove("is-selected");
      current.removeAttribute("aria-current");
      markItemRead(current);
      hideReadFromUnreadFilter(current);
    }
    if (selectedInput) selectedInput.value = "";
    refreshGroups();
    openLayout(false);
    setHidden(empty, false);
    if (history === "push") window.history.pushState({ announceId: null }, "", listHref());
    else if (history === "replace") window.history.replaceState({ announceId: null }, "", listHref());
    current?.focus();
  };

  retryButton?.addEventListener("click", () => {
    if (!retryState) return;
    loadAnnouncement(retryState.href, { history: "none", id: retryState.id });
  });

  const arrive = document.querySelector(".announce-detail.is-arrive");
  if (arrive) {
    const url = new URL(window.location.href);
    if (url.searchParams.has("arrive")) {
      url.searchParams.delete("arrive");
      window.history.replaceState({ announceId: arrive.dataset.announceId || null }, "", `${url.pathname}${url.search}${url.hash}`);
    }
    const clear = () => arrive.classList.remove("is-arrive");
    arrive.addEventListener("animationend", clear, { once: true });
    window.setTimeout(clear, 1600);
  }

  const selected = selectedItem();
  if (selected) {
    selected.scrollIntoView({ block: "nearest", behavior: "auto" });
    if (selected.classList.contains("is-unread")) {
      markItemReadOnServer(selected.dataset.id).then((marked) => {
        if (!marked) return;
        markItemRead(selected);
        markNotifyRead(selected.dataset.id);
        setUnreadCount(marked.unread_announcements ?? 0);
      });
    }
  }

  const restoreId = page.getAttribute("data-restore-id");
  if (restoreId && isDesktop() && !selected) {
    const restoreItem = itemById(restoreId);
    if (restoreItem && !restoreItem.hidden) {
      loadAnnouncement(restoreItem.href, { history: "replace", id: restoreId });
    }
  } else if (isDesktop() && !selected) {
    const preferred =
      visibleItems().find((item) => item.classList.contains("is-unread")) || visibleItems()[0];
    if (preferred) {
      loadAnnouncement(preferred.href, { history: "replace", id: preferred.dataset.id });
    }
  }

  document.addEventListener("click", (event) => {
    const item = event.target.closest(".announce-item");
    if (item && page.contains(item)) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      event.preventDefault();
      loadAnnouncement(item.href, { id: item.dataset.id });
      return;
    }
    if (event.target.closest("#announce-back")) {
      event.preventDefault();
      closeDetail();
    }
  });

  if (markAllForm) {
    markAllForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = markAllForm.querySelector('button[type="submit"]');
      if (submit) submit.disabled = true;
      try {
        const response = await fetch(markAllForm.getAttribute("action"), {
          method: "POST",
          headers: { "X-Requested-With": "fetch", Accept: "application/json" },
          body: new FormData(markAllForm),
        });
        const data = await response.json();
        if (!response.ok || !data.ok) {
          markAllForm.submit();
          return;
        }
        if (data.reload && data.redirect) {
          window.location.assign(data.redirect);
          return;
        }
        items().forEach((item) => {
          markItemRead(item);
        });
        markNotifyRead(null, true);
        setUnreadCount(data.unread_announcements ?? 0);
      } catch (_error) {
        markAllForm.submit();
      } finally {
        if (submit) submit.disabled = false;
      }
    });
  }

  window.addEventListener("popstate", () => {
    const match = window.location.pathname.match(/\/announcements\/(\d+)/);
    if (match) {
      const item = itemById(match[1]);
      if (item) loadAnnouncement(item.href, { history: "none", id: match[1] });
      else window.location.reload();
      return;
    }
    closeDetail({ history: "none" });
  });

  const applySearch = () => {
    if (!input) return;
    const query = input.value.trim().toLowerCase();
    items().forEach((item) => {
      const match = !query || (item.getAttribute("data-search") || "").includes(query);
      item.hidden = !match || item.dataset.caught === "1";
    });
    refreshGroups();
  };

  input?.addEventListener("input", applySearch);

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    if (target && (target.matches("input, textarea, select") || target.isContentEditable)) return;

    if (event.key === "Escape") {
      if (!isDesktop() && layout?.classList.contains("is-open")) {
        event.preventDefault();
        closeDetail();
      }
      return;
    }

    if (!listIsVisible()) return;
    const shown = visibleItems();
    if (!shown.length) return;
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Enter") return;

    const active = document.activeElement?.closest?.(".announce-item");
    const current = active && shown.includes(active) ? active : selectedItem();
    const index = Math.max(0, shown.indexOf(current));

    if (event.key === "Enter") {
      if (current && shown.includes(current) && document.activeElement === current) return;
      if (current) {
        event.preventDefault();
        loadAnnouncement(current.href, { id: current.dataset.id });
      }
      return;
    }

    event.preventDefault();
    const nextIndex = event.key === "ArrowDown" ? Math.min(shown.length - 1, index + (current ? 1 : 0)) : Math.max(0, index - 1);
    const next = shown[nextIndex];
    if (!next) return;
    next.focus();
    if (isDesktop()) loadAnnouncement(next.href, { id: next.dataset.id });
  });
})();
