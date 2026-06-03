import { AnimatedSection } from "@/components/animated-section";
import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  const legacyLoginUrl =
    process.env.NEXT_PUBLIC_LEGACY_LOGIN_URL ??
    (process.env.NODE_ENV === "development" ? "http://localhost:8080/login" : undefined);

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <AnimatedSection className="w-full max-w-md">
        <LoginForm legacyLoginUrl={legacyLoginUrl} />
      </AnimatedSection>
    </main>
  );
}
