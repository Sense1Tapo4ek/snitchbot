export function initDrawer(): void {
  if (typeof window === "undefined") return;
  const btn = document.querySelector<HTMLButtonElement>("[data-drawer-toggle]");
  const drawer = document.querySelector<HTMLElement>("[data-drawer]");
  const scrim = document.querySelector<HTMLElement>("[data-drawer-scrim]");
  if (!btn || !drawer || !scrim) return;

  const open = () => {
    drawer.classList.add("open");
    scrim.classList.add("open");
    btn.setAttribute("aria-expanded", "true");
    document.body.style.overflow = "hidden";
  };
  const close = () => {
    drawer.classList.remove("open");
    scrim.classList.remove("open");
    btn.setAttribute("aria-expanded", "false");
    document.body.style.overflow = "";
  };

  btn.addEventListener("click", () => {
    drawer.classList.contains("open") ? close() : open();
  });
  scrim.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });
}
