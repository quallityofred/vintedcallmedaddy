"use client";

import { FormEvent, useState } from "react";
import { AlertCircle, LoaderCircle, LockKeyhole, Ticket, User } from "lucide-react";
import { useRouter } from "next/navigation";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { safeNextPath } from "@/lib/auth";

type RegisterFormProps = {
  nextPath?: string;
};

async function getCsrfToken() {
  const response = await fetch("/api/v1/auth/csrf", {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error("Unable to prepare secure registration");
  }

  const payload = (await response.json()) as { csrf_token?: string };
  if (!payload.csrf_token) {
    throw new Error("Missing CSRF token");
  }
  return payload.csrf_token;
}

export function RegisterForm({ nextPath }: RegisterFormProps) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(false);

    if (password !== passwordConfirm) {
      setError("Passwords do not match.");
      return;
    }

    setIsSubmitting(true);
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/auth/register", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({
          username,
          password,
          password_confirm: passwordConfirm,
          invite_code: inviteCode,
        }),
      });

      if (!response.ok) {
        setError(response.status === 400 ? "Invite code is invalid or already used." : "Registration failed.");
        return;
      }

      setSuccess(true);
      router.push(safeNextPath(nextPath));
      router.refresh();
    } catch {
      setError("Unable to reach the registration API.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className="glass-panel">
      <CardHeader className="space-y-3">
        <div className="flex size-12 items-center justify-center rounded-2xl bg-emerald-300/10 text-emerald-200">
          <LockKeyhole className="size-5" />
        </div>
        <div>
          <h1 className="font-heading text-2xl font-medium leading-snug">Create account</h1>
          <CardDescription>
            Register with an invite code. The backend creates the same secure session cookie used by login.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <div className="relative">
              <User className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                autoComplete="username"
                className="pl-9"
                disabled={isSubmitting}
                id="username"
                onChange={(event) => setUsername(event.target.value)}
                required
                value={username}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="invite-code">Invite code</Label>
            <div className="relative">
              <Ticket className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                autoComplete="one-time-code"
                className="pl-9"
                disabled={isSubmitting}
                id="invite-code"
                onChange={(event) => setInviteCode(event.target.value)}
                required
                value={inviteCode}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              autoComplete="new-password"
              disabled={isSubmitting}
              id="password"
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password-confirm">Confirm password</Label>
            <Input
              autoComplete="new-password"
              disabled={isSubmitting}
              id="password-confirm"
              onChange={(event) => setPasswordConfirm(event.target.value)}
              required
              type="password"
              value={passwordConfirm}
            />
          </div>

          {error ? (
            <Alert className="border-red-300/20 bg-red-400/10 text-red-100" variant="destructive">
              <AlertCircle className="size-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {success ? (
            <Alert className="border-emerald-300/20 bg-emerald-400/10 text-emerald-100">
              <AlertDescription>Account created. Opening dashboard...</AlertDescription>
            </Alert>
          ) : null}

          <Button className="h-10 w-full" disabled={isSubmitting} type="submit">
            {isSubmitting ? (
              <>
                <LoaderCircle className="size-4 animate-spin" />
                Creating account
              </>
            ) : (
              "Create account"
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
