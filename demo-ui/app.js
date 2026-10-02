const actionButtons = [...document.querySelectorAll("[data-action]")];
const results = document.querySelector("#results");
const resetButton = document.querySelector("#reset-button");

const titles = {
  manifest: "Validate sample manifest",
  landing: "Build landing layout",
  pipeline: "Run synthetic analysis",
  safeguards: "Rehearse safeguards",
  reset: "Reset session",
  status: "Session status"
};

const notes = {
  manifest: "Manifest metadata validated locally. No genomic payload was downloaded.",
  landing: "Metadata-only placeholders. They are not inputs to the separate analysis run.",
  pipeline: "Local synthetic analysis. The demonstration stages are not biologically validated.",
  safeguards: "Checks ran against local synthetic stores and did not contact Azure."
};

const stateLabels = { ready: "Ready", running: "Running", passed: "Passed", failed: "Failed" };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function setState(name, state) {
  const badge = document.querySelector(`[data-status="${name}"]`);
  if (!badge) return;
  badge.dataset.state = state;
  badge.textContent = stateLabels[state] || state;
}

function props(pairs) {
  const list = el("dl", "result-props");
  pairs.forEach(([label, value]) => list.append(el("dt", "", label), el("dd", "", value)));
  return list;
}

function list(items) {
  const node = el("ul", "result-list");
  items.forEach(item => node.append(el("li", "", item)));
  return node;
}

function yesNo(value) {
  return value ? "Yes" : "No";
}

function humanize(key) {
  const text = String(key).replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatValue(value) {
  if (typeof value === "boolean") return yesNo(value);
  if (value === null || value === undefined) return "null";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function body(name, report) {
  switch (name) {
    case "manifest":
      return [props([
        ["Manifest", report.manifest_id],
        ["Synthetic identities", report.identity_count],
        ["Patient identifiers found", report.patient_identifying_values],
        ["Source reference", `${report.reference_build} ${report.reference_version}`]
      ])];
    case "landing":
      return [
        props([
          ["Run", report.run_id],
          ["Placeholder files", report.file_count],
          ["Paths preserved", yesNo(report.paths_preserved)],
          ["Inventory verified", yesNo(report.verified)],
          ["Reference", `${report.reference_build} ${report.reference_version}`]
        ]),
        list(report.example_paths)
      ];
    case "pipeline":
      return [
        props([
          ["Run", report.run_id],
          ["Terminal state", report.terminal_state],
          ["Workflow version", report.workflow_version],
          ["Reference build", report.reference_build],
          ["Reference version", report.reference_version],
          ["Manifest SHA-256", report.reference_manifest_sha256],
          ["Published outputs", report.output_count]
        ]),
        list(report.outputs)
      ];
    case "safeguards": {
      const table = el("table", "checks");
      const head = el("tr");
      ["Scenario", "Check", "Expected", "Observed", "Result"].forEach(h => head.append(el("th", "", h)));
      table.append(head);
      report.demonstrations.forEach(item => {
        const expected = item.expected_response || {};
        const actual = item.actual_response || {};
        Object.keys(expected).forEach((key, index) => {
          const matched = JSON.stringify(expected[key]) === JSON.stringify(actual[key]);
          const row = el("tr");
          const outcome = el("td", "", matched ? "Pass" : "Fail");
          outcome.dataset.passed = String(matched);
          row.append(
            el("td", "scenario", index === 0 ? humanize(item.name) : ""),
            el("td", "", humanize(key)),
            el("td", "mono", formatValue(expected[key])),
            el("td", "mono", formatValue(actual[key])),
            outcome
          );
          table.append(row);
        });
      });
      return [
        props([
          ["All scenarios passed", yesNo(report.all_passed)],
          ["Azure resources touched", yesNo(report.infrastructure_touched)]
        ]),
        table
      ];
    }
    default:
      return [];
  }
}

function addResult(name, report, error) {
  document.querySelector("#empty-state")?.remove();
  const card = el("article", "result");
  const head = el("div", "result-head");
  const badge = el("span", "status", error ? "Failed" : "Passed");
  badge.dataset.state = error ? "failed" : "passed";
  head.append(el("h3", "", titles[name] || name), badge);
  card.append(head);
  if (!error) card.append(...body(name, report));
  const note = el("p", "result-note", error || notes[name] || "");
  note.dataset.kind = error ? "error" : "info";
  card.append(note);
  results.prepend(card);
}

function showEmpty() {
  const empty = el("p", "empty", "No results yet. Run a step to see its output.");
  empty.id = "empty-state";
  results.replaceChildren(empty);
}

async function refreshStatus() {
  const response = await fetch("/api/status", { cache: "no-store" });
  if (!response.ok) throw new Error("Could not read session status.");
  const status = await response.json();
  Object.entries(status.actions).forEach(([name, action]) => {
    setState(name, action.state);
    if (action.state === "failed" && action.error) addResult(name, {}, action.error);
  });
  Object.entries(status.reports).forEach(([name, report]) => addResult(name, report));
}

actionButtons.forEach(button => {
  button.addEventListener("click", async () => {
    const name = button.dataset.action;
    button.disabled = true;
    button.textContent = "Running";
    setState(name, "running");
    try {
      const response = await fetch(`/api/run/${name}`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) {
        setState(name, "failed");
        addResult(name, {}, payload.error || "The step failed.");
      } else {
        Object.entries(payload.status.actions).forEach(([key, action]) => setState(key, action.state));
        addResult(name, payload.report);
      }
    } catch (error) {
      setState(name, "failed");
      addResult(name, {}, error.message || "The step failed.");
    } finally {
      button.disabled = false;
      button.textContent = button.dataset.label;
    }
  });
});

resetButton.addEventListener("click", async () => {
  resetButton.disabled = true;
  try {
    const response = await fetch("/api/reset", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Reset failed.");
    showEmpty();
    Object.entries(payload.actions).forEach(([key, action]) => setState(key, action.state));
  } catch (error) {
    addResult("reset", {}, error.message || "Reset failed.");
  } finally {
    resetButton.disabled = false;
  }
});

refreshStatus().catch(error => addResult("status", {}, error.message));
