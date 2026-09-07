// Remembers whether the conversation sidebar is collapsed, across reloads.
import { useState, useEffect } from "react";

const STORAGE_KEY = "askpesu-sidebar-collapsed";

export function useSidebarState() {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw === "true";
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, collapsed ? "true" : "false");
    } catch {
      /* noop */
    }
  }, [collapsed]);

  return { collapsed, setCollapsed };
}
