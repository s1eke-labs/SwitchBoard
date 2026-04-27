import { useCallback, useEffect, useState } from "react";

export function useElementSize<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const ref = useCallback((element: T | null) => {
    setNode(element);
  }, []);

  useEffect(() => {
    if (!node) return;
    const target = node;

    function updateSize(entry?: ResizeObserverEntry) {
      const rect = entry?.contentRect ?? target.getBoundingClientRect();
      const width = Math.floor(rect.width);
      const height = Math.floor(rect.height);
      setSize((current) => (current.width === width && current.height === height ? current : { width, height }));
    }

    updateSize();
    const observer = new ResizeObserver((entries) => updateSize(entries[0]));
    observer.observe(target);
    return () => observer.disconnect();
  }, [node]);

  return { ref, ...size };
}
