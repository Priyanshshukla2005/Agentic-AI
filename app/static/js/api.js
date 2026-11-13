// api.js - every call to our FastAPI backend lives here.
//
// All functions return the parsed JSON, or throw an ApiError with a `kind` the screens can turn
// into a friendly message:
//   "offline"  - the phone has no internet / the server cannot be reached
//   "timeout"  - the server took too long
//   "notFound" - 404 (e.g. the session was lost because the server restarted)
//   "incomplete" - 409 (profile not finished; error.detail.missing_fields says what is missing)
//   "server"   - 5xx (LLM down, rate limit...)
//   "client"   - other 4xx (bad input)

export class ApiError extends Error {
  constructor(kind, message, status = 0, detail = null) {
    super(message);
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

const DEFAULT_TIMEOUT_MS = 30000;
const PLAN_TIMEOUT_MS = 180000; // plan generation can take a while with a real LLM

async function request(method, path, body = undefined, timeoutMs = DEFAULT_TIMEOUT_MS) {
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    throw new ApiError("offline", "No internet connection");
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    if (err.name === "AbortError") throw new ApiError("timeout", "The server took too long");
    throw new ApiError("offline", "Could not reach the server"); // network error
  } finally {
    clearTimeout(timer);
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null; // empty or non-JSON body
  }
  if (response.ok) return data;

  const detail = data && data.detail !== undefined ? data.detail : null;
  const message = typeof detail === "string" ? detail : (detail && detail.message) || `HTTP ${response.status}`;
  let kind = "client";
  if (response.status === 404) kind = "notFound";
  else if (response.status === 409) kind = "incomplete";
  else if (response.status >= 500) kind = "server";
  throw new ApiError(kind, message, response.status, detail);
}

// ---------- Phase 2: intake chat ----------
export const createSession = (language) => request("POST", "/api/session", { language });
export const sendChat = (sessionId, message) => request("POST", "/api/chat", { session_id: sessionId, message });
export const getSession = (sessionId) => request("GET", `/api/session/${encodeURIComponent(sessionId)}`);
export const patchProfile = (sessionId, patch) =>
  request("PATCH", `/api/session/${encodeURIComponent(sessionId)}/profile`, patch);

// ---------- Phase 4: business plan ----------
export const createPlan = (sessionId, promptVersion = "plan_v4") =>
  request("POST", "/api/plan", { session_id: sessionId, prompt_version: promptVersion }, PLAN_TIMEOUT_MS);
export const getPlan = (sessionId) => request("GET", `/api/plan/${encodeURIComponent(sessionId)}`);
export const previewPlan = (profile, language, promptVersion = "plan_v4") =>
  request("POST", "/api/plan/preview", { profile, language, prompt_version: promptVersion }, PLAN_TIMEOUT_MS);
export const comparePlans = (profile, versions, language) =>
  request("POST", "/api/plan/compare", { profile, versions, language }, PLAN_TIMEOUT_MS * 2);

// ---------- Phase 5: demo data ----------
export const getSamples = () => request("GET", "/api/samples");
