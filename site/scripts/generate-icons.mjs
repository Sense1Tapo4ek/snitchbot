// One-off asset generator. Run: `node scripts/generate-icons.mjs`
// Generates apple-touch-icon.png (180×180) and og-image.png (1200×630).
import { readFile, writeFile } from "node:fs/promises";
import sharp from "sharp";

const root = new URL("..", import.meta.url);
const pub = (p) => new URL(`public/${p}`, root).pathname;

const faviconSvg = await readFile(pub("favicon.svg"));

// Apple touch icon — solid paper bg, vermillion 見, 180×180.
await sharp(faviconSvg, { density: 720 })
  .resize(180, 180)
  .png()
  .toFile(pub("apple-touch-icon.png"));

// OG image 1200×630 — washi-tint paper with large 見 kanji and wordmark.
const ogSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630">
  <defs>
    <radialGradient id="paper" cx="20%" cy="15%" r="90%">
      <stop offset="0%" stop-color="#fef7e6"/>
      <stop offset="55%" stop-color="#f2ebdc"/>
      <stop offset="100%" stop-color="#e3d9c1"/>
    </radialGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#paper)"/>
  <text x="1050" y="500" text-anchor="middle" font-family="serif" font-style="italic" font-size="520" fill="#b54b3c" opacity="0.18" font-weight="300">見</text>
  <g transform="translate(80, 220)">
    <text font-family="monospace" font-size="18" letter-spacing="4" fill="#6b5d48">SNITCHBOT · 通知</text>
    <text y="110" font-family="serif" font-style="italic" font-size="88" font-weight="400" fill="#1e1a15">Telemetry for Python,</text>
    <text y="210" font-family="serif" font-style="italic" font-size="88" font-weight="500" fill="#b54b3c">delivered to Telegram.</text>
    <text y="300" font-family="'Inter', sans-serif" font-size="22" fill="#3d352a">Crashes, load, anomalies — streamed to a chat you already have open.</text>
    <rect y="350" width="68" height="3" rx="1.5" fill="#b54b3c" opacity="0.9"/>
    <text y="400" font-family="monospace" font-size="20" fill="#1e1a15">$ uv add snitchbot</text>
  </g>
</svg>`;

await sharp(Buffer.from(ogSvg), { density: 150 })
  .resize(1200, 630)
  .png()
  .toFile(pub("og-image.png"));

console.log("generated: apple-touch-icon.png, og-image.png");
