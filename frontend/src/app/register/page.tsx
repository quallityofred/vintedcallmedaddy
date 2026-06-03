import { AnimatedSection } from "@/components/animated-section";
import { RegisterForm } from "@/components/register-form";
import { safeNextPath } from "@/lib/auth";

type RegisterPageProps = {
  searchParams?: Promise<{ next?: string | string[] }>;
};

export default async function RegisterPage({ searchParams }: RegisterPageProps) {
  const params = await searchParams;
  const rawNext = Array.isArray(params?.next) ? params?.next[0] : params?.next;
  const nextPath = safeNextPath(rawNext);

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <AnimatedSection className="w-full max-w-md">
        <RegisterForm nextPath={nextPath} />
      </AnimatedSection>
    </main>
  );
}
