"use client";

import { useCallback, useRef, useState } from "react";

export function useAsyncActions() {
  const pendingActionsRef = useRef<Set<string>>(new Set());
  const [pendingActions, setPendingActions] = useState<Set<string>>(() => new Set());

  const isPending = useCallback((key: string) => pendingActions.has(key), [pendingActions]);

  const hasPending = useCallback(
    (prefix?: string) => {
      if (!prefix) return pendingActions.size > 0;
      for (const key of pendingActions) {
        if (key.startsWith(prefix)) return true;
      }
      return false;
    },
    [pendingActions]
  );

  const runAction = useCallback(async <T,>(key: string, action: () => Promise<T>): Promise<T | undefined> => {
    if (pendingActionsRef.current.has(key)) return undefined;
    const acquired = new Set(pendingActionsRef.current);
    acquired.add(key);
    pendingActionsRef.current = acquired;
    setPendingActions(acquired);

    try {
      return await action();
    } finally {
      const released = new Set(pendingActionsRef.current);
      released.delete(key);
      pendingActionsRef.current = released;
      setPendingActions(released);
    }
  }, []);

  return { isPending, hasPending, pendingActions, runAction };
}
