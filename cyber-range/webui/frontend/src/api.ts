/** Same-origin console transport. Credentials and CSRF remain owned by Flask. */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const body = payload as { error?: unknown; detail?: unknown };
  const detail = body.error ?? body.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        typeof item === "string"
          ? item
          : item && typeof item === "object" && "msg" in item
            ? String(item.msg)
            : "",
      )
      .filter(Boolean);
    if (messages.length) return messages.slice(0, 4).join("; ");
  }
  return fallback;
}

export async function getJson<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    signal,
    headers: { Accept: "application/json" },
  });
  if (response.redirected && new URL(response.url).pathname === "/login") {
    window.location.assign(
      `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
    );
    throw new ApiError("Session expired", 401);
  }
  const payload: unknown = await response.json();
  if (!response.ok) {
    throw new ApiError(
      errorMessage(payload, `Request failed (${response.status})`),
      response.status,
    );
  }
  return payload as T;
}

export async function jsonRequest<T>(
  method: "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-CSRFToken":
        document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
          ?.content || "",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.redirected && new URL(response.url).pathname === "/login") {
    window.location.assign(
      `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
    );
    throw new Error("Session expired");
  }
  const payload: unknown = await response.json();
  if (!response.ok) {
    throw new ApiError(
      errorMessage(payload, `Action rejected (${response.status})`),
      response.status,
    );
  }
  return payload as T;
}

export function postJson<T>(path: string, body: unknown): Promise<T> {
  return jsonRequest<T>("POST", path, body);
}

export async function postForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "X-CSRFToken":
        document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
          ?.content || "",
    },
    body,
  });
  if (response.redirected && new URL(response.url).pathname === "/login") {
    window.location.assign(
      `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
    );
    throw new Error("Session expired");
  }
  const payload: unknown = await response.json();
  if (!response.ok) {
    throw new ApiError(
      errorMessage(payload, `Upload rejected (${response.status})`),
      response.status,
    );
  }
  return payload as T;
}
