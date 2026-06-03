export type AuthUser = {
  id: number;
  username: string;
  is_admin: boolean;
};

export function safeNextPath(nextPath: string | null | undefined): string {
  if (!nextPath || !nextPath.startsWith("/") || nextPath.startsWith("//")) {
    return "/dashboard";
  }
  return nextPath;
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const response = await fetch("/api/v1/auth/me", {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });

  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error("Unable to load current user");
  }

  const payload = (await response.json()) as { user?: AuthUser };
  return payload.user ?? null;
}
