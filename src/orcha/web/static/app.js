"use strict";
const $ = (id) => document.getElementById(id);
let workspace = null,
  busy = false,
  documentSequence = 0,
  forecastPoints = [],
  forecastLabel = "",
  forecastDays = 90;
const money = (value) => {
  if (value == null) return "—";
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: workspace?.summary?.currency || "INR",
      maximumFractionDigits: 2,
    }).format(Number(value));
  } catch {
    return String(value);
  }
};
const date = (value) =>
  value
    ? new Intl.DateTimeFormat("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
      }).format(new Date(value + "T00:00:00Z"))
    : "Not available";
const words = (value) => String(value || "").replaceAll("_", " ");
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}
function notice(message, error = false) {
  const node = $("notice");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.hidden = !message;
  const guideNotice = $("guide-notice");
  guideNotice.textContent = message;
  guideNotice.hidden = !message;
}
async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers:
      body === undefined
        ? {}
        : {
            "Content-Type": "application/json",
            "X-Orcha-Token": workspace?.csrf_token || "",
          },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw Error(
      "The local server returned an unreadable response. Please try again.",
    );
  }
  if (!response.ok) {
    const detail = data.detail;
    throw Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg || "Invalid input").join("; ")
          : "The request could not be completed. Please try again.",
    );
  }
  return data;
}
function setBusy(value) {
  busy = value;
  document
    .querySelectorAll("button, input, textarea, select")
    .forEach((node) => (node.disabled = value));
  $("submit").textContent = value
    ? "Checking the facts and forecast…"
    : "Find a steady way forward ↗";
  $("plan-form").setAttribute("aria-busy", String(value));
  if (!value) $("submit").disabled = !workspace;
}
function clearResult() {
  if (workspace)
    renderForecast(
      workspace.timeline,
      workspace.forecast_label || "Imported cash flow · before new updates",
    );
  $("result").hidden = true;
  $("result").replaceChildren();
  $("result-empty").hidden = false;
}
function renderWorkspace(data) {
  workspace = data;
  $("data-badge").textContent = data.is_demo
    ? "SYNTHETIC DEMO"
    : "IMPORTED WORKSPACE";
  $("balance").textContent = money(data.summary.balance);
  $("minimum").textContent = money(data.summary.minimum_balance);
  $("safe").textContent = money(data.summary.safe_to_spend);
  $("income").textContent = money(data.summary.upcoming_income);
  $("expenses").textContent = money(data.summary.upcoming_expenses);
  $("as-of").value = data.as_of;
  $("profile").replaceChildren(
    ...data.profiles.map((profile) => {
      const names = {
        demo_before: "Before the repair bill",
        demo_after: "With the repair bill",
      };
      const option = el(
        "option",
        "",
        data.is_demo
          ? names[profile.user_id] || profile.user_id
          : profile.user_id,
      );
      option.value = profile.user_id;
      return option;
    }),
  );
  $("profile").value = data.selected_user_id;
  $("profile").disabled = false;
  $("events").replaceChildren();
  const events = data.events || [];
  $("event-count").textContent =
    `${events.length} scheduled ${events.length === 1 ? "item" : "items"}`;
  for (const event of events) {
    const tr = el("tr");
    const label = el("td");
    const title = el("span", "event-label");
    title.append(
      el("span", "event-symbol", event.direction === "credit" ? "↙" : "↗"),
      document.createTextNode(event.label),
    );
    label.append(title);
    const status = el("td");
    status.append(el("span", "status-pill", words(event.status)));
    tr.append(
      label,
      el("td", "", date(event.date)),
      status,
      el(
        "td",
        "amount" + (event.direction === "credit" ? " income" : ""),
        (event.direction === "credit" ? "+" : "−") + money(event.amount),
      ),
    );
    $("events").append(tr);
  }
  if (!events.length) {
    const row = el("tr");
    const cell = el("td", "muted", "No scheduled activity in this forecast.");
    cell.colSpan = 4;
    row.append(cell);
    $("events").append(row);
  }
  $("examples").replaceChildren();
  for (const example of data.examples || []) {
    const button = el("button", "", example.title);
    button.type = "button";
    button.addEventListener("click", async () => {
      if (busy) return;
      setBusy(true);
      try {
        if (
          example.user_id !== workspace.selected_user_id ||
          example.as_of !== workspace.as_of
        ) {
          renderWorkspace(
            await api(
              "/api/workspace?" +
                new URLSearchParams({
                  user_id: example.user_id,
                  as_of: example.as_of,
                }),
            ),
          );
        }
        $("question").value =
          typeof example.question === "string"
            ? example.question
            : example.question?.text || "";
        $("documents").replaceChildren();
        for (const source of example.documents || [])
          addDocument(source.text, source.related_event_id, source.source_id);
        clearResult();
        $("question").focus();
      } catch (error) {
        notice(error.message, true);
      } finally {
        setBusy(false);
        $("question").focus();
      }
    });
    $("examples").append(button);
  }
  renderForecast(data.timeline, "Imported cash flow · before new updates");
  $("provider-status").textContent = data.providers.gemma_configured
    ? "Gemma is configured. Selected questions and text updates go to Google for interpretation."
    : "To interpret fresh questions, add GEMMA_API_KEY to the local .env file. Then reload this page.";
  $("import-files").textContent = data.import_files.join(" · ");
  clearResult();
}
function addDocument(text = "", related = "", sourceId) {
  if ($("documents").children.length >= 8) {
    notice("You can include up to eight text updates.", true);
    return;
  }
  documentSequence++;
  const source = sourceId || `upload_${documentSequence}`;
  const block = el("div", "document");
  block.dataset.sourceId = source;
  const head = el("div", "document-head");
  head.append(el("span", "", `Text update · ${source}`));
  const remove = el("button", "", "Remove");
  remove.type = "button";
  remove.setAttribute("aria-label", `Remove ${source}`);
  remove.addEventListener("click", () => {
    block.remove();
    clearResult();
  });
  head.append(remove);
  const input = el("textarea");
  input.value = text;
  input.maxLength = 8000;
  input.required = true;
  input.rows = 3;
  input.setAttribute("aria-label", `Text for ${source}`);
  input.placeholder =
    "Your electricity bill is INR 1,400, due on November 2, 2026.";
  const label = el("label", "", "Does this update an existing bill?");
  const relatedInput = el("select");
  relatedInput.append(el("option", "", "No — this is a new bill"));
  relatedInput.firstChild.value = "";
  for (const event of workspace?.amendable_events || []) {
    const option = el(
      "option",
      "",
      `${event.label} · ${date(event.date)} · ${money(event.amount)}`,
    );
    option.value = event.id;
    relatedInput.append(option);
  }
  if (
    related &&
    ![...relatedInput.options].some((option) => option.value === related)
  ) {
    const option = el("option", "", related);
    option.value = related;
    relatedInput.append(option);
  }
  relatedInput.value = related || "";
  relatedInput.setAttribute("aria-label", `Existing bill for ${source}`);
  label.append(relatedInput);
  block.append(head, input, label);
  $("documents").append(block);
  clearResult();
}

function renderForecast(points, label) {
  forecastPoints = points || [];
  forecastLabel = label;
  points = forecastPoints.slice(0, forecastDays);
  let holder = $("forecast");
  if (!holder) {
    holder = el("div", "forecast");
    holder.id = "forecast";
    document.querySelector(".ledger-card").before(holder);
  }
  holder.replaceChildren();
  if (!points?.length) {
    holder.hidden = true;
    return;
  }
  holder.hidden = false;
  const heading = el("div", "forecast-heading");
  heading.append(
    el("span", "", label),
    el("span", "", date(points[0].date) + " - " + date(points.at(-1).date)),
  );
  holder.append(heading);
  const controls = el("div", "chart-controls");
  for (const days of [30, 90]) {
    const button = el(
      "button",
      days === forecastDays ? "selected" : "",
      `${days} days`,
    );
    button.type = "button";
    button.setAttribute("aria-pressed", String(days === forecastDays));
    button.addEventListener("click", () => {
      forecastDays = days;
      renderForecast(forecastPoints, forecastLabel);
    });
    controls.append(button);
  }
  holder.append(controls);
  const width = Math.max(280, holder.clientWidth - 48),
    height = 220,
    left = 62,
    right = 16,
    top = 16,
    bottom = 30;
  const values = points.map((p) => Number(p.balance));
  const minimum = Number(workspace?.summary?.minimum_balance || 0);
  const min = Math.min(...values, minimum),
    max = Math.max(...values, minimum);
  const range = max - min || 1;
  const y = (value) =>
    height - bottom - ((value - min) / range) * (height - top - bottom);
  const x = (index) =>
    left + (index * (width - left - right)) / Math.max(1, values.length - 1);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  svg.setAttribute("role", "img");
  svg.setAttribute(
    "aria-label",
    "Daily forecast balance. Lowest " +
      money(Math.min(...values)) +
      ". Protected minimum " +
      money(minimum) +
      ".",
  );
  const shape = (tag, attributes) => {
    const node = document.createElementNS(svg.namespaceURI, tag);
    for (const [key, value] of Object.entries(attributes))
      node.setAttribute(key, String(value));
    svg.append(node);
    return node;
  };
  const labelAt = (px, py, text, anchor = "start") => {
    const node = shape("text", {
      x: px,
      y: py,
      "text-anchor": anchor,
      fill: "#52634f",
      "font-size": 11,
      "font-family": "Manrope, sans-serif",
    });
    node.textContent = text;
  };
  for (const value of [min, min + range / 2, max]) {
    shape("line", {
      x1: left,
      y1: y(value),
      x2: width - right,
      y2: y(value),
      stroke: "#e1e7d6",
      "stroke-width": 1,
    });
    const compact = new Intl.NumberFormat("en-IN", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
    labelAt(left - 10, y(value) + 3, compact, "end");
  }
  shape("line", {
    x1: left,
    y1: y(minimum),
    x2: width - right,
    y2: y(minimum),
    stroke: "#a78b62",
    "stroke-dasharray": "5 4",
    "stroke-width": 1,
  });
  shape("polyline", {
    points: values.map((value, index) => x(index) + "," + y(value)).join(" "),
    fill: "none",
    stroke: "#678450",
    "stroke-width": 2,
    "vector-effect": "non-scaling-stroke",
  });
  for (const index of [
    0,
    Math.floor((points.length - 1) / 2),
    points.length - 1,
  ])
    labelAt(
      x(index),
      height - 7,
      new Intl.DateTimeFormat("en-GB", {
        day: "numeric",
        month: "short",
        timeZone: "UTC",
      }).format(new Date(points[index].date + "T00:00:00Z")),
      index === 0 ? "start" : index === points.length - 1 ? "end" : "middle",
    );
  holder.append(svg);
  const foot = el("div", "forecast-heading");
  foot.append(
    el(
      "span",
      "",
      "Balance in " +
        (workspace?.summary?.currency || "INR") +
        " · Dashed line: protected minimum " +
        money(minimum),
    ),
    el("span", "", "Lowest " + money(Math.min(...values))),
  );
  holder.append(foot);
}
function detail(parent, title, text) {
  if (!text || text === "none") return;
  const p = el("p", "decision-detail");
  p.append(el("strong", "", title), document.createTextNode(text));
  parent.append(p);
}
function renderResult(data) {
  $("result-empty").hidden = true;
  const root = $("result");
  root.hidden = false;
  root.replaceChildren();
  const complete = data.status === "complete";
  root.append(
    el(
      "div",
      "result-kicker",
      complete
        ? "VERIFIED BY THE LOCAL ENGINE"
        : data.status === "needs_clarification"
          ? "A LITTLE MORE CLARITY"
          : "UNABLE TO COMPLETE",
    ),
  );
  root.append(
    el(
      "h3",
      "result-title",
      complete
        ? {
            affordable_now: "Within reach today.",
            affordable_later: "A little patience pays off.",
            affordable_with_plan: "A plan makes room.",
            not_affordable: "Keep your balance protected.",
          }[data.decision?.affordability_status] ||
            words(data.decision?.affordability_status)
        : data.status === "needs_clarification"
          ? "Let’s fill in the gaps."
          : "We couldn’t finish this forecast.",
    ),
  );
  root.append(el("p", "result-brief", data.brief));
  if (data.questions?.length) {
    const list = el("ul", "clarifications");
    data.questions.forEach((question) => list.append(el("li", "", question)));
    root.append(list);
    root.append(
      el(
        "p",
        "decision-detail",
        "Edit your question or text updates on the left, then run the planner again.",
      ),
    );
  }
  const decision = data.decision;
  if (decision) {
    const metrics = el("div", "decision-metrics");
    for (const [title, value] of [
      ["Safe payment amount", money(decision.amount_safe_to_pay)],
      [
        "Earliest full payment",
        decision.earliest_date_for_full_payment
          ? date(decision.earliest_date_for_full_payment)
          : "Not available",
      ],
    ]) {
      const metric = el("div");
      metric.append(el("span", "", title), el("strong", "", value));
      metrics.append(metric);
    }
    root.append(metrics);
    detail(
      root,
      "Payment approach",
      words(decision.recommended_payment_method),
    );
    detail(
      root,
      "Your plan",
      decision.payment_plan === "none"
        ? "No payment is recommended in this forecast."
        : decision.payment_plan
            .split("|")
            .map((payment) => {
              const [day, amount] = payment.split(":");
              return /^\d{4}-\d{2}-\d{2}$/.test(day)
                ? `${date(day)} · ${money(amount)}`
                : payment;
            })
            .join("\n"),
    );
    detail(root, "Spending adjustments", decision.spending_changes_needed);
  }
  if (data.evidence?.length) {
    const details = el("details");
    details.append(
      el(
        "summary",
        "",
        `Source evidence · ${data.evidence.length} verified facts`,
      ),
    );
    for (const fact of data.evidence) {
      const item = el("div", "evidence-fact");
      item.append(
        el(
          "small",
          "",
          `${fact.source_id}${fact.event_id ? " · " + fact.event_id : ""}`,
        ),
        el("div", "", `${words(fact.field)}: ${fact.value}`),
        el("blockquote", "", `“${fact.quote}”`),
      );
      details.append(item);
    }
    root.append(details);
  }
  const trace = el("details");
  trace.append(el("summary", "", "How this was worked out"));
  if (data.usage) {
    const usage = data.usage;
    const item = el("div", "trace-row");
    item.append(
      el("strong", "", "Gemma interpretation"),
      el(
        "small",
        "",
        `${usage.model} · ${usage.api_calls} API ${usage.api_calls === 1 ? "call" : "calls"} · ${usage.total_tokens} tokens${usage.cached ? " · cached response" : ""}`,
      ),
    );
    trace.append(item);
  }
  for (const [index, route] of (data.routing || []).entries()) {
    const item = el("div", "trace-row");
    item.append(
      el(
        "strong",
        "",
        `${String(index + 1).padStart(2, "0")} · ${words(route.selected_action)}`,
      ),
      el(
        "small",
        "",
        `${route.source === "laya" ? "Laya accepted" : "Local fallback"} · ${words(route.reason)}${route.proposed_action ? " · proposed " + words(route.proposed_action) : ""}${route.latency_ms ? " · " + Math.round(route.latency_ms) + " ms" : ""}`,
      ),
    );
    trace.append(item);
  }
  if (!data.routing?.length && !data.usage)
    trace.append(
      el(
        "p",
        "trace-row",
        "No model calls or routing decisions were recorded.",
      ),
    );
  if (data.actions?.length) {
    const actions = el("div", "trace-row");
    actions.append(
      el("strong", "", "Local workflow"),
      el("small", "", data.actions.map(words).join(" / ")),
    );
    trace.append(actions);
  }
  root.append(trace);
  if (data.timeline?.length)
    renderForecast(
      data.timeline,
      data.forecast_label || "With your updates · before this purchase",
    );
}
async function loadWorkspace() {
  if (busy) return;
  setBusy(true);
  clearResult();
  try {
    notice("");
    const params = new URLSearchParams();
    if ($("profile").value) params.set("user_id", $("profile").value);
    if ($("as-of").value) params.set("as_of", $("as-of").value);
    const data = await api("/api/workspace?" + params);
    renderWorkspace(data);
  } catch (error) {
    notice(error.message, true);
    if (workspace) {
      $("profile").value = workspace.selected_user_id;
      $("as-of").value = workspace.as_of;
    }
  } finally {
    setBusy(false);
  }
}
$("profile").addEventListener("change", () => {
  $("documents").replaceChildren();
  if (!busy) loadWorkspace();
});
$("as-of").addEventListener("change", () => {
  if (!busy && $("as-of").value && $("as-of").validity.valid) loadWorkspace();
  else if (workspace) $("as-of").value = workspace.as_of;
});
$("add-document").addEventListener("click", () => addDocument());
$("txt-input").addEventListener("change", async (event) => {
  for (const file of event.target.files) {
    if (!file.name.toLowerCase().endsWith(".txt") || file.size > 32000) {
      notice("Choose a .txt file with up to 8,000 characters.", true);
      continue;
    }
    const text = await file.text();
    if (text.length > 8000) {
      notice(`${file.name} is too long. Use up to 8,000 characters.`, true);
      continue;
    }
    addDocument(text);
  }
  event.target.value = "";
});
$("csv-input").addEventListener("change", async (event) => {
  const selected = [...event.target.files];
  if (!selected.length) return;
  const required = workspace?.import_files || [];
  const names = selected.map((file) => file.name);
  if (
    required.length &&
    (required.some((name) => !names.includes(name)) ||
      selected.length !== required.length)
  ) {
    notice(
      `Select all ${required.length} CSV files together: ${required.join(", ")}. Download the sample ZIP and extract it first.`,
      true,
    );
    event.target.value = "";
    return;
  }
  if (selected.some((file) => file.size > 5000000)) {
    notice("Each CSV must be smaller than 5 MB.", true);
    event.target.value = "";
    return;
  }
  setBusy(true);
  notice("Reading and validating your CSVs…");
  try {
    const files = [];
    for (const file of selected)
      files.push({ name: file.name, content: await file.text() });
    const data = await api("/api/import", { files });
    renderWorkspace(data);
    $("question").value = "";
    $("documents").replaceChildren();
    $("guide").close();
    notice(
      "CSVs imported for this local session. Imports and drafts are not saved across server restarts.",
    );
  } catch (error) {
    notice(error.message, true);
  } finally {
    setBusy(false);
    event.target.value = "";
  }
});
$("reset").addEventListener("click", async () => {
  setBusy(true);
  try {
    renderWorkspace(await api("/api/reset", {}));
    $("question").value = "";
    $("documents").replaceChildren();
    notice(
      "Synthetic demo restored. Imported CSVs and draft updates have been cleared.",
    );
  } catch (error) {
    notice(error.message, true);
  } finally {
    setBusy(false);
  }
});
$("plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !workspace) return;
  const documents = [...$("documents").children].map((block) => {
    const related = block.querySelector("select").value.trim();
    return {
      source_id: block.dataset.sourceId,
      text: block.querySelector("textarea").value.trim(),
      ...(related ? { related_event_id: related } : {}),
    };
  });
  setBusy(true);
  notice("");
  $("result-empty").hidden = true;
  $("result").hidden = false;
  const loading = el("div", "result-empty");
  loading.append(
    el("div", "loading-spinner"),
    el("h3", "", "A little perspective, on its way."),
    el(
      "p",
      "",
      "Interpreting your updates and checking the local financial forecast. This can take a moment.",
    ),
  );
  $("result").replaceChildren(loading);
  try {
    renderResult(
      await api("/api/assist", {
        user_id: workspace.selected_user_id,
        as_of: $("as-of").value,
        question: {
          source_id: "purchase_question",
          text: $("question").value.trim(),
        },
        documents,
      }),
    );
  } catch (error) {
    renderResult({ status: "unavailable", brief: error.message });
  } finally {
    setBusy(false);
    $("result").setAttribute("tabindex", "-1");
    $("result").focus({ preventScroll: true });
    if (window.innerWidth <= 800)
      $("result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }
});
$("plan-form").addEventListener("input", clearResult);
$("plan-form").addEventListener("change", clearResult);
$("import-open").addEventListener("click", () => $("guide").showModal());
$("guide-close").addEventListener("click", () => $("guide").close());
$("guide").addEventListener("click", (event) => {
  if (event.target === $("guide")) $("guide").close();
});
document.querySelectorAll("nav a").forEach((link) =>
  link.addEventListener("click", () => {
    document
      .querySelectorAll("nav a")
      .forEach((item) => item.classList.toggle("nav-active", item === link));
  }),
);
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (forecastPoints.length) renderForecast(forecastPoints, forecastLabel);
  }, 150);
});
loadWorkspace();
