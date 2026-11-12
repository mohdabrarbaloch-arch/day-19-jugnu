/* ==========================================================================
   Jugnu — frontend
   Vanilla JS, no build step. Everything the UI shows comes from the API;
   nothing is invented client-side.
   ========================================================================== */

(() => {
  "use strict";

  // ---------- tiny helpers ----------

  const $ = (id) => document.getElementById(id);

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const TOKEN_KEY = "jugnu.token";
  const USER_KEY = "jugnu.user";

  const state = {
    token: localStorage.getItem(TOKEN_KEY) || "",
    user: JSON.parse(localStorage.getItem(USER_KEY) || "null"),
    authMode: "login",
    lastResult: null,
    busy: false,
  };

  // ---------- api ----------

  async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;

    const res = await fetch(path, { ...options, headers });

    if (res.status === 204) return null;

    let body = null;
    const type = res.headers.get("content-type") || "";
    if (type.includes("application/json")) {
      body = await res.json().catch(() => null);
    }

    if (!res.ok) {
      const message =
        (body && (body.detail || body.message)) || `Request failed (${res.status})`;
      const error = new Error(typeof message === "string" ? message : "Request failed");
      error.status = res.status;
      throw error;
    }
    return body;
  }

  // ---------- toast ----------

  let toastTimer = null;
  function toast(message) {
    const node = $("toast");
    node.textContent = message;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      node.hidden = true;
    }, 2400);
  }

  // ---------- view switching ----------

  function show(which) {
    $("hero").hidden = which !== "hero";
    $("results").hidden = which !== "results";
    $("loading").hidden = which !== "loading";
    $("notice").hidden = which !== "notice";
    $("history").hidden = which !== "history";
  }

  function notice(message, { retry = false } = {}) {
    $("notice-text").textContent = message;
    $("notice-retry").hidden = !retry;
    show("notice");
  }

  // ---------- auth ----------

  function renderAuthState() {
    const btn = $("btn-auth");
    if (state.user) {
      btn.textContent = state.user.display_name || "Account";
      btn.title = "Sign out";
    } else {
      btn.textContent = "Sign in";
      btn.title = "";
    }
  }

  function openAuth(mode = "login") {
    state.authMode = mode;
    applyAuthMode();
    $("auth-error").hidden = true;
    $("auth-form").reset();
    $("auth-modal").hidden = false;
    setTimeout(() => $("auth-email").focus(), 40);
  }

  function closeAuth() {
    $("auth-modal").hidden = true;
  }

  function applyAuthMode() {
    const isRegister = state.authMode === "register";
    $("auth-title").textContent = isRegister ? "Create an account" : "Sign in";
    $("auth-sub").textContent = isRegister
      ? "Save your searches and keep them in one place."
      : "Save your searches and pick up where you left off.";
    $("auth-submit").textContent = isRegister ? "Create account" : "Sign in";
    $("field-name").hidden = !isRegister;
    $("auth-switch-text").textContent = isRegister ? "Already have an account?" : "New here?";
    $("auth-switch").textContent = isRegister ? "Sign in" : "Create an account";
    $("auth-password").autocomplete = isRegister ? "new-password" : "current-password";
  }

  async function submitAuth(event) {
    event.preventDefault();
    const errorNode = $("auth-error");
    const submit = $("auth-submit");
    errorNode.hidden = true;
    submit.disabled = true;

    const payload = {
      email: $("auth-email").value.trim(),
      password: $("auth-password").value,
    };
    if (state.authMode === "register") {
      payload.display_name = $("auth-name").value.trim() || payload.email.split("@")[0];
    }

    try {
      const path = state.authMode === "register" ? "/api/auth/register" : "/api/auth/login";
      const data = await api(path, { method: "POST", body: JSON.stringify(payload) });
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem(TOKEN_KEY, state.token);
      localStorage.setItem(USER_KEY, JSON.stringify(state.user));
      renderAuthState();
      closeAuth();
      toast(state.authMode === "register" ? "Welcome to Jugnu" : "Signed in");
    } catch (err) {
      errorNode.textContent = err.message;
      errorNode.hidden = false;
    } finally {
      submit.disabled = false;
    }
  }

  function signOut() {
    state.token = "";
    state.user = null;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    renderAuthState();
    toast("Signed out");
  }

  // ---------- search ----------

  function setLoadingStep(step) {
    const order = ["search", "read", "write"];
    const index = order.indexOf(step);
    document.querySelectorAll("#loading-steps li").forEach((li) => {
      const i = order.indexOf(li.dataset.step);
      li.classList.toggle("active", i === index);
      li.classList.toggle("done", i < index);
    });
    const labels = {
      search: "Searching the web…",
      read: "Reading the pages…",
      write: "Writing the answer…",
    };
    $("loading-text").textContent = labels[step] || "Working…";
  }

  async function runSearch(question, threadId) {
    if (state.busy) return;
    const q = (question || "").trim();
    if (q.length < 3) {
      toast("Ask a slightly longer question");
      return;
    }

    state.busy = true;
    $("ask-send").disabled = true;
    show("loading");
    setLoadingStep("search");

    // The backend does all three phases in one request, so this is a
    // best-effort progress hint rather than real telemetry.
    const timers = [
      setTimeout(() => setLoadingStep("read"), 900),
      setTimeout(() => setLoadingStep("write"), 2400),
    ];

    try {
      const payload = { question: q };
      if (threadId) payload.thread_id = threadId;

      const data = await api("/api/search", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      timers.forEach(clearTimeout);
      renderResult(data);
      show("results");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      timers.forEach(clearTimeout);
      if (err.status === 401) {
        notice("That search belongs to another account. Sign in to continue it.", {
          retry: false,
        });
      } else if (err.status === 429) {
        notice(err.message, { retry: true });
      } else {
        notice(err.message || "Something went wrong. Try again.", { retry: true });
      }
    } finally {
      state.busy = false;
      $("ask-send").disabled = false;
    }
  }

  // ---------- rendering ----------

  /**
   * Turn "[1]" markers in the answer text into clickable citation pills.
   * Built with DOM nodes, never innerHTML, so a hostile page title cannot
   * inject markup.
   */
  function renderAnswerText(container, text) {
    container.textContent = "";
    const paragraphs = text.split(/\n{2,}/);

    paragraphs.forEach((para) => {
      const p = el("p");
      const parts = para.split(/(\[\d+\])/g);

      parts.forEach((part) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (match) {
          const num = match[1];
          const link = el("a", "cite", num);
          link.href = `#source-${num}`;
          link.setAttribute("aria-label", `Source ${num}`);
          link.addEventListener("click", (event) => {
            event.preventDefault();
            const target = document.getElementById(`source-${num}`);
            if (target) {
              target.scrollIntoView({ behavior: "smooth", block: "center" });
              target.style.borderColor = "var(--accent)";
              setTimeout(() => {
                target.style.borderColor = "";
              }, 1400);
            }
          });
          p.appendChild(link);
        } else if (part) {
          p.appendChild(document.createTextNode(part));
        }
      });

      if (p.childNodes.length) container.appendChild(p);
    });
  }

  function renderResult(data) {
    state.lastResult = data;

    // The API nests the answer inside the query record.
    const query = data.query;
    const answer = query.answer;

    $("results-q").textContent = query.question;

    const meta = $("results-meta");
    meta.textContent = "";
    const bits = [
      `${query.source_count} source${query.source_count === 1 ? "" : "s"}`,
      `${query.latency_ms} ms`,
      query.provider_used,
    ];
    bits.forEach((bit) => meta.appendChild(el("span", null, bit)));

    $("answer-provider").textContent =
      query.answer_provider === "extractive"
        ? "Answer · extractive"
        : `Answer · ${query.answer_provider}`;
    renderAnswerText($("answer-body"), answer);

    // Sources
    const list = $("source-list");
    list.textContent = "";
    $("sources-count").textContent = `(${query.sources.length})`;

    query.sources.forEach((source, index) => {
      const li = el("li", "source");
      li.id = `source-${index + 1}`;

      const link = el("a", "source-title", source.title || source.domain);
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      li.appendChild(link);

      const metaRow = el("div", "source-meta");
      metaRow.appendChild(el("span", "source-domain", source.domain));
      const badge = el(
        "span",
        `badge ${source.fetched_ok ? "read" : "snippet"}`,
        source.fetched_ok ? "read" : "snippet only"
      );
      metaRow.appendChild(badge);
      if (source.published_at) {
        metaRow.appendChild(el("span", null, formatWhen(source.published_at)));
      }
      li.appendChild(metaRow);

      if (source.snippet) {
        li.appendChild(el("p", "source-snippet", source.snippet));
      }

      list.appendChild(li);
    });

    // Follow-ups
    const followups = $("followups");
    const chips = $("followup-chips");
    chips.textContent = "";
    if (data.follow_ups && data.follow_ups.length) {
      data.follow_ups.forEach((q) => {
        const chip = el("button", "chip", q);
        chip.type = "button";
        chip.addEventListener("click", () => runSearch(q, data.thread_id || undefined));
        chips.appendChild(chip);
      });
      followups.hidden = false;
    } else {
      followups.hidden = true;
    }

    // Share only makes sense for a saved thread.
    $("btn-share").hidden = !data.thread_id;
  }

  // ---------- copy / share ----------

  async function copyAnswer() {
    if (!state.lastResult) return;
    const query = state.lastResult.query;
    const text = query.answer;
    const sources = query.sources
      .map((s, i) => `[${i + 1}] ${s.title} — ${s.url}`)
      .join("\n");
    try {
      await navigator.clipboard.writeText(`${text}\n\nSources:\n${sources}`);
      toast("Copied with sources");
    } catch {
      toast("Could not copy — select the text instead");
    }
  }

  async function shareThread() {
    if (!state.lastResult || !state.lastResult.thread_id) return;
    try {
      const data = await api(`/api/threads/${state.lastResult.thread_id}/share`, {
        method: "POST",
      });
      const url = `${location.origin}/s/${data.share_slug}`;
      await navigator.clipboard.writeText(url);
      toast("Share link copied");
    } catch (err) {
      toast(err.message || "Could not create a share link");
    }
  }

  // ---------- history ----------

  async function openHistory() {
    if (!state.user) {
      openAuth("login");
      return;
    }
    show("history");
    const list = $("history-list");
    list.textContent = "";
    $("history-empty").hidden = true;

    try {
      const threads = await api("/api/threads");
      if (!threads.length) {
        $("history-empty").hidden = false;
        return;
      }
      threads.forEach((thread) => {
        const li = el("li", "history-item");

        const open = el("button", "history-open");
        open.type = "button";
        open.appendChild(el("span", "history-q", thread.title));
        open.appendChild(el("span", "history-when", formatWhen(thread.updated_at)));
        open.addEventListener("click", () => loadThread(thread.id));
        li.appendChild(open);

        const del = el("button", "history-del", "×");
        del.type = "button";
        del.setAttribute("aria-label", `Delete ${thread.title}`);
        del.addEventListener("click", async () => {
          try {
            await api(`/api/threads/${thread.id}`, { method: "DELETE" });
            li.remove();
            if (!list.children.length) $("history-empty").hidden = false;
            toast("Deleted");
          } catch (err) {
            toast(err.message || "Could not delete");
          }
        });
        li.appendChild(del);

        list.appendChild(li);
      });
    } catch (err) {
      notice(err.message || "Could not load your history");
    }
  }

  async function loadThread(threadId) {
    try {
      const thread = await api(`/api/threads/${threadId}`);
      if (!thread.queries.length) {
        notice("That search is empty.");
        return;
      }
      const last = thread.queries[thread.queries.length - 1];
      renderResult({
        thread_id: thread.id,
        query: last,
        answer: last.answer,
        follow_ups: last.follow_ups || [],
      });
      show("results");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      notice(err.message || "Could not open that search");
    }
  }

  function formatWhen(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    const diff = (Date.now() - date.getTime()) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  // ---------- textarea behaviour ----------

  function autoGrow(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }

  // ---------- wiring ----------

  function init() {
    renderAuthState();

    const form = $("ask-form");
    const input = $("question");

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      runSearch(input.value);
    });

    input.addEventListener("input", () => autoGrow(input));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    document.querySelectorAll("#chips .chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        input.value = chip.textContent;
        autoGrow(input);
        runSearch(chip.textContent);
      });
    });

    $("btn-copy").addEventListener("click", copyAnswer);
    $("btn-share").addEventListener("click", shareThread);

    $("btn-history").addEventListener("click", openHistory);
    $("history-close").addEventListener("click", () => {
      show(state.lastResult ? "results" : "hero");
    });

    $("btn-auth").addEventListener("click", () => {
      if (state.user) signOut();
      else openAuth("login");
    });

    $("auth-form").addEventListener("submit", submitAuth);
    $("auth-switch").addEventListener("click", () => {
      state.authMode = state.authMode === "login" ? "register" : "login";
      applyAuthMode();
      $("auth-error").hidden = true;
    });

    document.querySelectorAll("[data-close]").forEach((node) => {
      node.addEventListener("click", closeAuth);
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !$("auth-modal").hidden) closeAuth();
    });

    $("notice-retry").addEventListener("click", () => {
      const q = state.lastResult ? state.lastResult.query.question : input.value;
      runSearch(q);
    });

    // Deep link: /s/<slug> renders a shared thread.
    const shareMatch = location.pathname.match(/^\/s\/([A-Za-z0-9_-]+)$/);
    if (shareMatch) {
      api(`/api/public/threads/${shareMatch[1]}`)
        .then((thread) => {
          const last = thread.queries[thread.queries.length - 1];
          if (!last) {
            notice("That shared search is empty.");
            return;
          }
          renderResult({
            thread_id: "",
            query: last,
            answer: last.answer,
            follow_ups: last.follow_ups || [],
          });
          show("results");
        })
        .catch(() => notice("That share link is not available."));
    }

    input.focus();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
