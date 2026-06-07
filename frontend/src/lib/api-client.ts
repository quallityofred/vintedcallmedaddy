export class ApiRequestError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

async function getCsrfToken(): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiRequestError("Unable to obtain CSRF token. Refresh the page and try again.", response.status);
  }
  const data = (await response.json()) as { csrf_token?: string };
  if (!data.csrf_token) {
    throw new ApiRequestError("Unable to obtain CSRF token. Refresh the page and try again.", response.status);
  }
  return data.csrf_token;
}

async function readApiError(response: Response): Promise<ApiRequestError> {
  const data = (await response.json().catch(() => ({}))) as {
    code?: string;
    detail?: string;
    message?: string;
  };
  if (response.status === 403) {
    return new ApiRequestError(
      "Action rejected by CSRF/auth; refresh the page and try again through the UI.",
      response.status,
      data.code,
    );
  }
  return new ApiRequestError(
    data.message || data.detail || `Request failed (${response.status})`,
    response.status,
    data.code,
  );
}

export async function csrfFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const csrfToken = await getCsrfToken();
  const headers = new Headers(init.headers);
  headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(input, {
    ...init,
    credentials: "same-origin",
    headers,
  });
  if (!response.ok) {
    throw await readApiError(response);
  }
  return response;
}

export async function checkMonitorNow(monitorId: number): Promise<{
  ok: boolean;
  code: string;
  message: string;
  retry_after?: number;
}> {
  const response = await csrfFetch(`/api/v1/monitors/${monitorId}/check-now`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  return response.json();
}
