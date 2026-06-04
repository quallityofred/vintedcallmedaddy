"use client";

import { useEffect, useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Domain {
  domain: string;
  flag: string;
  code?: string;
  label?: string;
  host?: string;
  aliases?: string[];
}

const MARKETPLACE_LABELS: Record<string, string> = {
  fr: "France",
  de: "Germany",
  pl: "Poland / CEE",
  es: "Spain",
  it: "Italy",
  nl: "Netherlands / Benelux",
  pt: "Portugal",
  uk: "United Kingdom",
};

function getMarketplaceLabel(domain: Domain) {
  const code = domain.code?.toLowerCase();
  if (code && MARKETPLACE_LABELS[code]) {
    return {
      title: `${code.toUpperCase()} - ${MARKETPLACE_LABELS[code]}`,
      subtitle: domain.host || domain.domain,
    };
  }

  return {
    title: domain.label || domain.host || domain.domain,
    subtitle: domain.host && domain.label ? domain.host : domain.domain,
  };
}

function getDomainId(domain: string) {
  return `domain-${domain.replace(/[^a-z0-9]/gi, "-")}`;
}

export function DomainSelection({
  selectedDomains,
  onSelectionChange,
}: {
  selectedDomains: string[];
  onSelectionChange: (domains: string[]) => void;
}) {
  const [domains, setDomains] = useState<Domain[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  let statusLabel = `Target Domains (${selectedDomains.length} / ${domains.length})`;
  if (loading) {
    statusLabel = "Loading target domains";
  } else if (error) {
    statusLabel = "Target domains unavailable";
  }

  const fetchDomains = async () => {
    setLoading(true);
    setError(false);
    try {
      const response = await fetch("/api/v1/monitors/domains", {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new Error("Unable to load target domains");
      }
      const data = (await response.json()) as Domain[] | { domains?: Domain[] };
      const nextDomains = Array.isArray(data) ? data : data.domains || [];
      setDomains(nextDomains);
      onSelectionChange(selectedDomains.filter((domain) => nextDomains.some((item) => item.domain === domain)));
    } catch {
      setError(true);
      setDomains([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchDomains();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleDomain = (domain: string) => {
    if (selectedDomains.includes(domain)) {
      onSelectionChange(selectedDomains.filter((d) => d !== domain));
    } else {
      onSelectionChange([...selectedDomains, domain]);
    }
  };

  const toggleAll = () => {
    if (domains.length === 0) {
      return;
    }
    if (selectedDomains.length === domains.length) {
      onSelectionChange([]);
    } else {
      onSelectionChange(domains.map((d) => d.domain));
    }
  };

  return (
    <div className="grid gap-3 rounded-2xl border border-white/10 bg-white/[0.025] p-3 sm:p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Label className="text-sm font-medium">{statusLabel}</Label>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Select the unique Vinted marketplaces this monitor should check.
          </p>
        </div>
        <button
          type="button"
          onClick={toggleAll}
          disabled={loading || error || domains.length === 0}
          className="self-start rounded-full border border-emerald-300/20 px-3 py-1.5 text-xs font-medium text-emerald-100 transition hover:border-emerald-200/50 hover:bg-emerald-300/10 disabled:cursor-not-allowed disabled:opacity-50 sm:self-auto"
        >
          {selectedDomains.length === domains.length ? "Deselect all" : "Select all"}
        </button>
      </div>

      {error ? (
        <div className="rounded-lg border border-red-300/20 bg-red-400/10 p-3 text-sm text-red-100">
          <p>Target domains could not be loaded.</p>
          <Button className="mt-3" onClick={fetchDomains} size="sm" type="button" variant="secondary">
            Retry
          </Button>
        </div>
      ) : null}

      {!loading && !error && domains.length === 0 ? (
        <p className="rounded-lg border border-white/10 bg-black/10 p-3 text-sm text-muted-foreground">
          No target marketplaces are currently available.
        </p>
      ) : null}

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {domains.map((d) => {
          const isSelected = selectedDomains.includes(d.domain);
          const { title, subtitle } = getMarketplaceLabel(d);
          const id = getDomainId(d.domain);
          return (
            <label
              key={d.domain}
              htmlFor={id}
              className={cn(
                "group flex cursor-pointer items-start gap-3 rounded-2xl border p-3 transition-all focus-within:border-emerald-200/70 focus-within:ring-2 focus-within:ring-emerald-300/20",
                isSelected
                  ? "border-emerald-300/55 bg-emerald-300/12 shadow-lg shadow-emerald-950/20"
                  : "border-white/10 bg-black/10 hover:border-emerald-200/35 hover:bg-white/[0.05]"
              )}
            >
              <Checkbox
                id={id}
                checked={isSelected}
                className="mt-0.5"
                onCheckedChange={() => toggleDomain(d.domain)}
              />
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-foreground">{title}</span>
                <span className="mt-0.5 block truncate text-xs text-muted-foreground">{subtitle}</span>
                {d.aliases && d.aliases.length > 0 ? (
                  <span className="mt-1 block text-[11px] text-emerald-100/65">
                    Includes {d.aliases.length} alias{d.aliases.length === 1 ? "" : "es"}
                  </span>
                ) : null}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
