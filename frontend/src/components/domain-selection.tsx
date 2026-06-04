"use client";

import { useEffect, useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

interface Domain {
  domain: string;
  flag: string;
  code?: string;
  label?: string;
  host?: string;
  aliases?: string[];
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
    <div className="grid gap-3 rounded-lg border border-white/5 bg-white/[0.02] p-3">
      <div className="flex items-center justify-between">
        <Label className="text-sm font-medium">{statusLabel}</Label>
        <button
          type="button"
          onClick={toggleAll}
          disabled={loading || error || domains.length === 0}
          className="text-xs text-emerald-200 hover:text-emerald-100 hover:underline"
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

      <div className="grid grid-cols-2 gap-2">
        {domains.map((d) => (
          <div key={d.domain} className="flex items-center space-x-2">
            <Checkbox
              id={d.domain}
              checked={selectedDomains.includes(d.domain)}
              onCheckedChange={() => toggleDomain(d.domain)}
            />
            <Label htmlFor={d.domain} className="text-sm font-normal cursor-pointer">
              {d.flag ? `${d.flag} ` : ""}
              {d.label || d.host || d.domain}
            </Label>
          </div>
        ))}
      </div>
    </div>
  );
}
