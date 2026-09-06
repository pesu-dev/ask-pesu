import { useRef, useEffect, useCallback } from "react";

export function useTextareaResize(value: string, minRows: number = 1) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const lineHeight = parseInt(getComputedStyle(el).lineHeight) || 20;
    const minHeight = lineHeight * minRows;
    el.style.height = `${Math.max(minHeight, Math.min(el.scrollHeight, lineHeight * 8))}px`;
  }, [minRows]);

  useEffect(() => {
    resize();
  }, [value, resize]);

  return ref;
}
