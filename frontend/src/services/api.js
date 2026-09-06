/**
 * Backend API client.
 * The base URL comes from VITE_API_URL (see .env.example). No hardcoded
 * localhost URLs live in component code.
 */

const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

const INVESTIGATE_TIMEOUT_MS = 180_000; // RCA involves an LLM call; allow generous time
const HEALTH_TIMEOUT_MS = 5_000;

export const QUESTION_MAX_LENGTH = 500;

// Real workflow stage ids (must match backend NODE_STAGE_IDS / SSE events).
export const STAGES = [
  { id: "question_analysis", label: "Understanding question" },
  { id: "incident_retrieval", label: "Searching incidents" },
  { id: "deployment_correlation", label: "Correlating deployment" },
  { id: "log_retrieval", label: "Analyzing logs" },
  { id: "runbook_retrieval", label: "Checking runbooks" },
  { id: "evidence_aggregation", label: "Aggregating evidence" },
  { id: "evidence_validation", label: "Validating evidence" },
  { id: "rca_generation", label: "Generating RCA" },
];

async function fetchWithTimeout(url, options = {}, timeoutMs = INVESTIGATE_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function userSafeError(body, fallback) {
  return (body && body.message) || fallback;
}

/**
 * Run an RCA investigation (non-streaming). Returns:
 * { status, investigation, report, message }
 */
export async function investigate(question) {
  let response;
  try {
    response = await fetchWithTimeout(`${API_URL}/investigate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  } catch {
    throw new Error(
      "The investigation timed out or the backend is unreachable. Please try again."
    );
  }

  let body = null;
  try {
    body = await response.json();
  } catch {
    /* non-JSON response handled below */
  }

  if (response.status === 429) {
    throw new Error(
      userSafeError(body, "Too many investigations in a short time. Please wait a moment and retry.")
    );
  }
  if (!response.ok) {
    throw new Error(
      userSafeError(body, "The backend could not complete this investigation. Please try again later.")
    );
  }
  if (!body || (!body.investigation && !body.report)) {
    throw new Error("The backend returned an empty result. Please try again.");
  }
  return body;
}

/**
 * Run an RCA investigation with REAL SSE progress streaming.
 * @param {string} question
 * @param {(event: {type: string, stage?: string, payload?: object}) => void} onEvent
 */
export async function investigateStream(question, onEvent) {
  let response;
  try {
    response = await fetchWithTimeout(`${API_URL}/investigate/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question }),
    });
  } catch {
    throw new Error(
      "The investigation timed out or the backend is unreachable. Please try again."
    );
  }

  if (response.status === 429) {
    throw new Error("Too many investigations in a short time. Please wait a moment and retry.");
  }
  if (!response.ok || !response.body) {
    throw new Error("The backend could not start this investigation. Please try again later.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completedPayload = null;

  const handleChunk = (block) => {
    const lines = block.split("\n");
    let event = null;
    let data = "";
    for (const line of lines) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!event || !data) return;
    let parsed = null;
    try {
      parsed = JSON.parse(data);
    } catch {
      return;
    }
    if (event === "investigation_completed") {
      completedPayload = parsed;
      onEvent({ type: "completed" });
    } else if (event === "investigation_error") {
      throw new Error(parsed.message || "The investigation failed. Please try again.");
    } else if (event === "investigation_started") {
      onEvent({ type: "started" });
    } else if (event.endsWith("_completed")) {
      onEvent({ type: "stage_completed", stage: event.slice(0, -"_completed".length) });
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      handleChunk(block);
    }
  }

  if (!completedPayload) {
    throw new Error("The investigation ended without a result. Please try again.");
  }
  return completedPayload;
}

/** Lightweight health probe used by the header status indicator. */
export async function checkHealth() {
  try {
    const response = await fetchWithTimeout(
      `${API_URL}/health`,
      { method: "GET" },
      HEALTH_TIMEOUT_MS
    );
    if (!response.ok) return { online: false };
    const body = await response.json();
    return { online: true, qdrant: body.qdrant, geminiConfigured: body.gemini_configured };
  } catch {
    return { online: false };
  }
}
