import { animate, inView } from "motion";

const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

if (!reduce) {
  document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((el) => {
    el.style.opacity = "0";
    el.style.transform = "translateY(12px)";
    inView(el, () => {
      const delayMs = Number(el.dataset.revealDelay || 0);
      animate(
        el,
        { opacity: 1, transform: "translateY(0px)" },
        { duration: 0.5, delay: delayMs / 1000, easing: "ease-out" },
      );
    });
  });
}
