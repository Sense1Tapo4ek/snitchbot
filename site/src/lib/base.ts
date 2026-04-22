// Prepends Astro's configured base path to an absolute-rooted URL.
export const withBase = (path: string): string => {
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
};
