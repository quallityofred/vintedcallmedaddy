"use client";

import { ReactNode, useEffect, useState } from "react";
import { LoaderCircle, ShieldAlert } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { AuthUser, fetchCurrentUser } from "@/lib/auth";

type AuthGuardProps = {
  children: ReactNode;
  requireAdmin?: boolean;
};

function authRedirect(pathname: string) {
  return `/login?next=${encodeURIComponent(pathname)}`;
}

export function AuthGuard({ children, requireAdmin = false }: AuthGuardProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function checkAuth() {
      try {
        const currentUser = await fetchCurrentUser();
        if (!active) return;

        if (!currentUser) {
          router.replace(authRedirect(pathname));
          return;
        }

        if (requireAdmin && !currentUser.is_admin) {
          router.replace("/dashboard");
          return;
        }

        setUser(currentUser);
      } catch {
        if (!active) return;
        setError("Unable to verify your session. Please sign in again.");
        router.replace(authRedirect(pathname));
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void checkAuth();
    return () => {
      active = false;
    };
  }, [pathname, requireAdmin, router]);

  if (loading || !user) {
    return (
      <main className="flex min-h-screen items-center justify-center px-6 py-12">
        <Card className="glass-panel w-full max-w-md">
          <CardContent className="flex items-center gap-3 p-6 text-sm text-muted-foreground">
            <LoaderCircle className="size-5 animate-spin text-emerald-200" />
            Verifying session...
          </CardContent>
        </Card>
      </main>
    );
  }

  if (error) {
    return (
      <main className="flex min-h-screen items-center justify-center px-6 py-12">
        <Alert className="max-w-md border-red-300/20 bg-red-400/10 text-red-100" variant="destructive">
          <ShieldAlert className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </main>
    );
  }

  return <>{children}</>;
}
