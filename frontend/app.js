// Frontend for the safety dashboard (plain JavaScript, no libraries).
//
// The browser only collects the inputs and shows the results.
// The risk assessment, Gemma's proposal, the safety check and the final
// decision are all produced by the Python backend (see backend/pipeline.py).

const FIELDS = [
  "gas_lel", "gas_trend", "ventilation_pct", "fan_status",
  "hot_work_permit", "maintenance_fault", "shift_condition",
];

let config = null;         // preset and field labels from /api/config
let lastRequest = null;    // the request (as JSON text) behind the results on screen

document.addEventListener("DOMContentLoaded", start);

function byId(id) {
  return document.getElementById(id);
}

// ---------- Start-up ----------

async function start() {
  try {
    config = await callApi("/api/config");
  } catch (error) {
    showError("Cannot reach the backend. Start it with: python3 backend/server.py");
    return;
  }

  fillPresetList();
  loadPreset(config.default_preset);
  showGemmaStatus();

  byId("preset").addEventListener("change", (event) => loadPreset(event.target.value));
  byId("reset-button").addEventListener("click", () => loadPreset(config.default_preset));
  byId("scenario-form").addEventListener("input", onFormChanged);
  byId("scenario-form").addEventListener("submit", (event) => {
    event.preventDefault(); // stay on this page
    runAnalysis();
  });
}

function showGemmaStatus() {
  // Only shown when there is a problem, so the page stays clean.
  if (!config.gemma.available) {
    const status = byId("gemma-status");
    status.textContent = "Gemma is not available: " + config.gemma.message +
      " Without it there is no agent proposal, and the safety check uses its own safe default.";
    status.hidden = false;
  }
}

// ---------- Scenario inputs ----------

function fillPresetList() {
  for (const [key, preset] of Object.entries(config.presets)) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = preset.label;
    byId("preset").appendChild(option);
  }
}

function loadPreset(key) {
  const preset = config.presets[key];
  byId("preset").value = key;
  for (const field of FIELDS) {
    const value = preset.values[field];
    byId(field).value = value === null ? "" : String(value);
  }
  onFormChanged();
}

function readInputs() {
  // Values are sent exactly as entered. The backend checks them and treats
  // blank or invalid values as "not reported".
  const inputs = {};
  for (const field of FIELDS) {
    const element = byId(field);
    if (element.validity.badInput) {
      inputs[field] = "unreadable entry"; // text the number box could not read
    } else {
      inputs[field] = element.value === "" ? null : element.value;
    }
  }
  return inputs;
}

function onFormChanged() {
  // Highlight inputs that are not reported.
  for (const field of FIELDS) {
    byId(field).classList.toggle("is-missing", byId(field).value === "");
  }
  // Warn when the results on screen no longer match the inputs.
  const changed = lastRequest !== null && JSON.stringify(readInputs()) !== lastRequest;
  byId("notice").textContent = "The inputs have changed. Press Run Analysis to update the results.";
  byId("notice").hidden = !changed;
}

// ---------- Running an analysis ----------

async function runAnalysis() {
  const inputs = readInputs();
  const button = byId("run-button");
  button.disabled = true;
  button.textContent = "Analysing…";
  try {
    const result = await callApi("/api/analyse", { inputs: inputs, proposal_source: "gemma" });
    lastRequest = JSON.stringify(inputs);
    byId("results").innerHTML = resultsHtml(result);
    onFormChanged();
  } catch (error) {
    showError("The analysis could not be run: " + error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Run Analysis";
  }
}

async function callApi(url, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function showError(message) {
  lastRequest = null;
  byId("notice").hidden = true;
  byId("results").innerHTML = `<p class="error">${escapeHtml(message)}</p>`;
}

// ---------- Results ----------

function resultsHtml(result) {
  return riskSection(result) + proposalSection(result.proposal) +
    safetyCheckSection(result.gate) + finalSection(result.final_decision);
}

function riskSection(result) {
  const risk = result.risk;
  const notes = result.input_notes.map((note) => `<p class="small muted">${escapeHtml(note)}</p>`).join("");
  return `
    <section class="result">
      <h2>Risk Assessment</h2>
      <p><span class="badge large risk-${escapeHtml(risk.category)}">${escapeHtml(risk.category)}</span></p>
      <p>${escapeHtml(risk.explanation)}</p>
      ${notes}
    </section>`;
}

function proposalSection(proposal) {
  // The agent's answer is shown in readable form. The safety check reads the
  // original answer itself; this is only for display.
  const answer = parseJsonObject(proposal.raw_output);
  let body;
  if (proposal.error) {
    body = `<p class="muted">${escapeHtml(proposal.error)}</p>`;
  } else if (answer === null || typeof answer.action !== "string") {
    body = `<p class="muted">The agent's answer could not be read as a proposal.</p>`;
  } else {
    const confidence = typeof answer.confidence === "number" && answer.confidence >= 0 && answer.confidence <= 1
      ? `<p class="small muted">Confidence: ${Math.round(answer.confidence * 100)}% (the safety check does not rely on this)</p>`
      : "";
    body = `
      <p class="action">${readableAction(answer.action)}</p>
      <p>${escapeHtml(typeof answer.reason === "string" ? answer.reason : "")}</p>
      ${confidence}`;
  }
  return `
    <section class="result">
      <h2>Agent Proposal</h2>
      ${body}
    </section>`;
}

function safetyCheckSection(gate) {
  const word = gate.decision === "ACCEPTED" ? "Accepted" : "Rejected";
  return `
    <section class="result">
      <h2>Safety Check</h2>
      <p><span class="badge large gate-${escapeHtml(gate.decision)}">${word}</span></p>
      <p>${escapeHtml(gate.plain_explanation)}</p>
    </section>`;
}

function finalSection(finalDecision) {
  return `
    <section class="result final">
      <h2>Final Decision</h2>
      <p class="action">${readableAction(finalDecision.action)}</p>
      <p>${escapeHtml(finalDecision.explanation)}</p>
    </section>`;
}

// ---------- Small helpers ----------

function readableAction(action) {
  // RECOMMEND_EVACUATION_REVIEW -> RECOMMEND EVACUATION REVIEW (escaped for safety)
  return escapeHtml(action.replaceAll("_", " "));
}

function parseJsonObject(text) {
  try {
    const value = JSON.parse(text);
    return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

function escapeHtml(value) {
  // Agent output is untrusted, so every value is escaped before it is shown.
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
