// Client-side tab switcher. Handles click + arrow-key navigation.
// Each case has two DOM siblings (code panel + TG panel) identified by data-case="key".

document.querySelectorAll<HTMLElement>("[data-tabs]").forEach((tabList) => {
  const tabs = Array.from(tabList.querySelectorAll<HTMLElement>('[role="tab"]'));
  const root = tabList.closest<HTMLElement>("[data-tabs-root]");
  if (!root) return;

  const activate = (key: string): void => {
    tabs.forEach((t) => {
      const active = t.dataset.case === key;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", active ? "true" : "false");
      t.setAttribute("tabindex", active ? "0" : "-1");
    });
    root.querySelectorAll<HTMLElement>("[data-case-panel]").forEach((p) => {
      p.setAttribute("data-hidden", p.dataset.case === key ? "false" : "true");
    });
    const desc = root.querySelector<HTMLElement>("[data-case-desc]");
    if (desc) {
      desc.querySelectorAll<HTMLElement>("[data-desc]").forEach((n) => {
        n.setAttribute("data-hidden", n.dataset.desc === key ? "false" : "true");
      });
    }
  };

  tabList.addEventListener("click", (e) => {
    const t = (e.target as HTMLElement).closest<HTMLElement>('[role="tab"]');
    if (!t || !t.dataset.case) return;
    activate(t.dataset.case);
    t.focus();
  });

  tabList.addEventListener("keydown", (e) => {
    const current = document.activeElement as HTMLElement | null;
    if (!current || !tabs.includes(current)) return;
    const idx = tabs.indexOf(current);
    let next = idx;
    if (e.key === "ArrowRight") next = (idx + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (idx - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    else return;
    e.preventDefault();
    const key = tabs[next].dataset.case;
    if (key) activate(key);
    tabs[next].focus();
  });
});
