export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const ACCESS_TOKEN_KEY = "personal_cloud_access_token";
const REFRESH_TOKEN_KEY = "personal_cloud_refresh_token";

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;

  const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!response.ok) {
    clearTokens();
    return null;
  }

  const body = (await response.json()) as { access_token: string; refresh_token: string };
  setTokens(body.access_token, body.refresh_token);
  return body.access_token;
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      // FastAPI/Pydantic 422 validation errors.
      return body.detail
        .map((entry) => (typeof entry === "object" && entry && "msg" in entry ? String((entry as { msg: unknown }).msg) : JSON.stringify(entry)))
        .join("; ");
    }
  } catch {
    // fall through to the generic message below
  }
  return response.statusText || `request failed with status ${response.status}`;
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const token = getAccessToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  // GET /api/health intentionally returns 503 with a valid body when a
  // component is unhealthy — that's data, not a request failure.
  if (path === "/api/health" && !response.ok && response.status === 503) {
    return (await response.json()) as T;
  }

  if (response.status === 401 && retry && getRefreshToken() && path !== "/api/auth/refresh") {
    const newToken = await refreshAccessToken();
    if (newToken) {
      return request<T>(path, init, false);
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export function apiPut<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

export function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  return request<T>(path, { method: "POST", body: formData });
}

/** Thrown when an upload is cancelled through its AbortSignal. */
export class RequestAborted extends Error {
  constructor() {
    super("upload cancelled");
  }
}

/**
 * POST a multipart body with upload-progress events (fetch cannot report them). Handles the
 * same one-time token refresh as the other helpers, and can be cancelled with `signal`.
 */
export function apiUploadWithProgress<T>(
  path: string,
  formData: FormData,
  onProgress?: (loaded: number, total: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  function attempt(retry: boolean): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      if (signal?.aborted) {
        reject(new RequestAborted());
        return;
      }
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE_URL}${path}`);
      const token = getAccessToken();
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress?.(event.loaded, event.total);
      };
      xhr.onload = () => {
        if (xhr.status === 401 && retry && getRefreshToken()) {
          void refreshAccessToken().then((fresh) => {
            if (fresh) resolve(attempt(false));
            else reject(new ApiError(401, "your session expired - log in again"));
          });
          return;
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve((xhr.status === 204 ? undefined : JSON.parse(xhr.responseText)) as T);
          return;
        }
        let detail = "";
        try {
          const body = JSON.parse(xhr.responseText) as { detail?: unknown };
          if (typeof body.detail === "string") detail = body.detail;
        } catch {
          // not JSON
        }
        reject(new ApiError(xhr.status, detail || `upload failed with status ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error("upload failed: network error"));
      xhr.onabort = () => reject(new RequestAborted());
      signal?.addEventListener("abort", () => xhr.abort(), { once: true });
      xhr.send(formData);
    });
  }
  return attempt(true);
}

export function apiDownloadUrl(fileId: string): string {
  return `${API_BASE_URL}/api/files/${fileId}/download`;
}
