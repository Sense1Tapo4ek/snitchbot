export function initToc(): void {
  if (typeof window === "undefined") return;

  const headings = Array.from(
    document.querySelectorAll<HTMLElement>("main.reading h2[id], main.reading h3[id]")
  );
  const links = new Map<string, HTMLAnchorElement>();
  document.querySelectorAll<HTMLAnchorElement>("[data-toc-link]").forEach(a => {
    links.set(a.dataset.tocLink!, a);
  });
  if (!headings.length || !links.size) return;

  const order = new Map<string, number>();
  headings.forEach((h, i) => order.set(h.id, i));

  const visible = new Set<string>();
  let current: string | null = null;

  const setActive = (id: string | null) => {
    if (id === current) return;
    if (current) links.get(current)?.classList.remove("active");
    if (id) links.get(id)?.classList.add("active");
    current = id;
  };

  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const id = (e.target as HTMLElement).id;
      if (e.isIntersecting) visible.add(id);
      else visible.delete(id);
    }
    if (visible.size === 0) return;
    let topId: string | null = null;
    let topIdx = Infinity;
    for (const id of visible) {
      const idx = order.get(id) ?? Infinity;
      if (idx < topIdx) { topIdx = idx; topId = id; }
    }
    setActive(topId);
  }, { rootMargin: "-20% 0px -70% 0px", threshold: 0 });

  headings.forEach(h => io.observe(h));
}
