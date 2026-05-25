import { useEffect, useState } from "react";
import { DEMO_ENABLED as DEMO_DEFAULT } from "@/lib/demo-responses";

const KEY = "askpesu-demo-enabled";

/**
 * Reactive demo-mode toggle backed by localStorage. The initial value falls
 * back to DEMO_ENABLED from src/lib/demo-responses.ts on first visit. Users
 * can flip it at runtime from the Settings dialog without editing code.
 */
export function useDemoMode() {
  const [enabled, setEnabledState] = useState<boolean>(() => {
    if (typeof window === "undefined") return DEMO_DEFAULT;
    const raw = localStorage.getItem(KEY);
    if (raw === null) return DEMO_DEFAULT;
    return raw === "true";
  });

  useEffect(() => {
    try {
      localStorage.setItem(KEY, String(enabled));
    } catch {
      /* ignore quota / SSR */
    }
  }, [enabled]);

  return { demoEnabled: enabled, setDemoEnabled: setEnabledState };
}
