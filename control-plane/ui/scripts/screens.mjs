// Screenshot smoke test. Start the app yourself first (mock mode), then:
//   node scripts/screens.mjs http://localhost:3000
// Writes screenshots/<name>-<light|dark>.png at 390x844 (2x).
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const base = (process.argv[2] ?? "http://localhost:3000").replace(/\/$/, "");
const pages = [
  ["fleet", "/"],
  ["app-detail", "/apps/intake-portal"],
  ["change", "/changes/chg_042"],
  ["security", "/security"],
];

mkdirSync("screenshots", { recursive: true });
const browser = await chromium.launch();
let failed = 0;
for (const scheme of ["light", "dark"]) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, colorScheme: scheme });
  const page = await ctx.newPage();
  for (const [name, path] of pages) {
    const res = await page.goto(base + path, { waitUntil: "networkidle" });
    await page.evaluate(() => document.fonts.ready);
    const status = res?.status() ?? 0;
    if (status >= 400) failed++;
    const file = `screenshots/${name}-${scheme}.png`;
    // Grow the viewport to the page height so fixed bars render at the bottom, as on a phone.
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    await page.setViewportSize({ width: 390, height: Math.max(844, height) });
    await page.screenshot({ path: file });
    await page.setViewportSize({ width: 390, height: 844 });
    console.log(`${status} ${path} -> ${file}`);
  }
  await ctx.close();
}
await browser.close();
process.exit(failed ? 1 : 0);
