"use client";

import { useEffect, useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

interface Domain {
  domain: string;
  flag: string;
}

export function DomainSelection({
  selectedDomains,
  onSelectionChange,
}: {
  selectedDomains: string[];
  onSelectionChange: (domains: string[]) => void;
}) {
  const [domains, setDomains] = useState<Domain[]>([]);

  useEffect(() => {
    async function fetchDomains() {
      try {
        const response = await fetch("/api/v1/monitors/domains");
        if (response.ok) {
          const data = (await response.json()) as Domain[];
          setDomains(data);
        }
      } catch (error) {
        console.error("Failed to fetch domains:", error);
      }
    }
    void fetchDomains();
  }, []);

  const toggleDomain = (domain: string) => {
    if (selectedDomains.includes(domain)) {
      onSelectionChange(selectedDomains.filter((d) => d !== domain));
    } else {
      onSelectionChange([...selectedDomains, domain]);
    }
  };

  const toggleAll = () => {
    if (selectedDomains.length === domains.length) {
      onSelectionChange([]);
    } else {
      onSelectionChange(domains.map((d) => d.domain));
    }
  };

  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between">
        <Label>Target Domains ({selectedDomains.length} / {domains.length})</Label>
        <button
          type="button"
          onClick={toggleAll}
          className="text-xs text-emerald-200 hover:underline"
        >
          {selectedDomains.length === domains.length ? "Deselect all" : "Select all"}
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {domains.map((d) => (
          <div key={d.domain} className="flex items-center space-x-2">
            <Checkbox
              id={d.domain}
              checked={selectedDomains.includes(d.domain)}
              onCheckedChange={() => toggleDomain(d.domain)}
            />
            <Label htmlFor={d.domain} className="font-normal">
              {d.flag} {d.domain}
            </Label>
          </div>
        ))}
      </div>
    </div>
  );
}
