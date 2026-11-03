"use client";
import { useEffect, useRef, useState } from "react";

export function useWidth<T extends HTMLElement>(initial = 600) {
  const ref = useRef<T>(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0]?.contentRect.width;
      if (cw && Math.abs(cw - w) > 0.5) setW(Math.floor(cw));
    });
    ro.observe(el);
    setW(Math.floor(el.getBoundingClientRect().width) || initial);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return [ref, w] as const;
}
