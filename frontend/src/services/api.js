/**
 * Backend API client.
 *
 * Authentication: a server-side session in an HttpOnly, SameSite=Strict cookie
 * (set by POST /auth/login). No credential lives in this bundle or in browser
 * storage. The API is reached through the same origin (`/api`, proxied by Vite
 * in development and by the reverse proxy in production) so the cookie is
 * first-party. State-changing requests send the session's CSRF token, which is
 * kept only in memory (re-fetched from /auth/me after a reload).
 */

const API_URL = (import.meta.env.VITE_API_URL || "/api").replace(/\/+$/, "");

let csrfToken = null;
let onUnauthorized = null;

/** Register a callback for 401 responses (session expired / signed out). */
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

function headers(extra = {}, unsafe = false) {
  return unsafe && csrfToken ? { ...extra, "X-CSRF-Token": csrfToken } : extra;
}

const INVESTIGATE_TIMEOUT_MS = 180_000; // RCA involves LLM calls; allow generous time
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
    return await fetch(url, { credentials: "same-origin", ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function userSafeError(body, fallback) {
  return (body && body.message) || fallback;
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function authError(response, body) {
  if (response.status === 401) {
    onUnauthorized?.();
    return userSafeError(body, "Your session has ended. Please sign in again.");
  }
  if (response.status === 403) return userSafeError(body, "You are not permitted to do this.");
  return null;
}

/** Generic JSON call; throws Error(message) on failure. */
async function call(path, { method = "GET", body, timeout = 30_000 } = {}) {
  const unsafe = method !== "GET";
  let response;
  try {
    response = await fetchWithTimeout(`${API_URL}${path}`, {
      method,
      headers: headers(body !== undefined ? { "Content-Type": "application/json" } : {}, unsafe),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }, timeout);
  } catch {
    throw new Error("The backend is unreachable. Please try again.");
  }
  const data = await readJson(response);
  const authMessage = authError(response, data);
  if (authMessage) throw new Error(authMessage);
  if (!response.ok) throw new Error(userSafeError(data, `Request failed (${response.status}).`));
  return data;
}

// --------------------------------------------------------------------------- auth

export async function login(username, password) {
  let response;
  try {
    response = await fetchWithTimeout(`${API_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }, 15_000);
  } catch {
    throw new Error("The backend is unreachable. Please try again.");
  }
  const data = await readJson(response);
  if (!response.ok) throw new Error(userSafeError(data, "Sign-in failed."));
  csrfToken = data.csrf_token;
  return data;
}

/** Current identity, or null when not signed in. */
export async function me() {
  let response;
  try {
    response = await fetchWithTimeout(`${API_URL}/auth/me`, {}, 10_000);
  } catch {
    return null;
  }
  if (!response.ok) return null;
  const data = await readJson(response);
  csrfToken = data?.csrf_token || null;
  return data;
}

export async function logout() {
  try {
    await call("/auth/logout", { method: "POST" });
  } finally {
    csrfToken = null;
  }
}

// --------------------------------------------------------------------------- investigations

/**
 * Run an RCA investigation (non-streaming). Returns:
 * { status, investigation, report, message }
 */
export async function investigate(question) {
  let response;
  try {
    response = await fetchWithTimeout(`${API_URL}/investigate`, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }, true),
      body: JSON.stringify({ question }),
    });
  } catch {
    throw new Error(
      "The investigation timed out or the backend is unreachable. Please try again."
    );
  }

  const body = await readJson(response);
  const authMessage = authError(response, body);
  if (authMessage) throw new Error(authMessage);
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
      headers: headers({ "Content-Type": "application/json", Accept: "text/event-stream" }, true),
      body: JSON.stringify({ question }),
    });
  } catch {
    throw new Error(
      "The investigation timed out or the backend is unreachable. Please try again."
    );
  }

  const authMessage = authError(response, null);
  if (authMessage) throw new Error(authMessage);
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

// --------------------------------------------------------------------------- tools and approvals

export const listTools = () => call("/tools");
export const invokeTool = (name, args) => call(`/tools/${encodeURIComponent(name)}/invoke`,
  { method: "POST", body: { args } });
export const listActions = () => call("/actions");
export const proposeAction = (tool, args) => call("/actions", { method: "POST", body: { tool, args } });
export const approveAction = (id, argsHash, note) =>
  call(`/actions/${encodeURIComponent(id)}/approve`, { method: "POST", body: { args_hash: argsHash, note } });
export const rejectAction = (id, argsHash, note) =>
  call(`/actions/${encodeURIComponent(id)}/reject`, { method: "POST", body: { args_hash: argsHash, note } });
export const executeAction = (id, args) =>
  call(`/actions/${encodeURIComponent(id)}/execute`, { method: "POST", body: { args } });

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
