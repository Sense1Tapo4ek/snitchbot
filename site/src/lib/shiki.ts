import { createHighlighter, type Highlighter } from "shiki";

let highlighterPromise: Promise<Highlighter> | null = null;

const LANGS = ["python", "bash", "yaml", "text", "json", "toml"] as const;
export type SupportedLang = typeof LANGS[number];

export async function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({
      themes: ["dark-plus"],
      langs: [...LANGS],
    });
  }
  return highlighterPromise;
}

export async function highlight(code: string, lang: SupportedLang = "python"): Promise<string> {
  const hl = await getHighlighter();
  return hl.codeToHtml(code.trim(), { lang, theme: "dark-plus" });
}
