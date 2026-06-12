"use client";

import { useEffect, useState } from "react";
import { Activity, Bell, Clock, Radar } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";

import { AnimatedSection } from "@/components/animated-section";
import { DashboardCard } from "@/components/dashboard-card";

interface Stats {
  active_monitors_count: number;
  paused_monitors_count: number;
  items_today_count: number;
  total_items_count: number;
  last_found_at: string | null;
  telegram_status: {
    configured: boolean;
    running: boolean;
  };
}

export function DashboardStats() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    async function fetchStats() {
      try {
        const response = await fetch("/api/v1/dashboard/stats", {
          cache: "no-store",
          credentials: "same-origin",
        });
        if (response.status === 401) {
          router.replace(`/login?next=${encodeURIComponent(pathname)}`);
          return;
        }
        if (!response.ok) {
          throw new Error("API error");
        }
        const data = (await response.json()) as Stats;
        setStats(data);
      } catch {
        setErrorText("Unavailable");
      }
    }
    void fetchStats();

    const interval = setInterval(fetchStats, 30 * 1000);
    return () => clearInterval(interval);
  }, [pathname, router]);

  const cards = [
    {
      title: "Active monitors",
      value: stats
        ? `${stats.active_monitors_count} / ${stats.active_monitors_count + stats.paused_monitors_count}`
        : errorText
          ? errorText
          : "Loading...",
      icon: Radar,
    },
    {
      title: "Items today",
      value: stats ? stats.items_today_count.toString() : errorText ? errorText : "Loading...",
      icon: Activity,
    },
    {
      title: "Telegram status",
      value: stats
        ? stats.telegram_status.running
          ? "Running"
          : stats.telegram_status.configured
            ? "Stopped"
            : "Not set"
        : errorText
          ? errorText
          : "Loading...",
      icon: Bell,
    },
    {
      title: "Last discovery",
      value: stats
        ? stats.last_found_at
          ? new Date(stats.last_found_at).toLocaleTimeString()
          : "Never"
        : errorText
          ? errorText
          : "Loading...",
      icon: Clock,
    },
  ];

  return (
    <AnimatedSection className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => (
        <DashboardCard key={card.title} {...card} />
      ))}
    </AnimatedSection>
  );
}
