// Captures the website's screenshots from a dev server seeded by seed_demo.py.
//   npm i playwright@1.48.2 && node scripts/site/shoot.mjs http://localhost:8080 site/assets/shots
// Uses Microsoft Edge (channel "msedge"); change it to "chrome" if that is what you have.
// Only crops of the real app are saved: nothing is retouched or mocked up.

import { chromium } from "playwright";
import fs from "node:fs";

const base = process.argv[2] || "http://localhost:8080";
const out = process.argv[3] || "site/assets/shots";
fs.mkdirSync(out, { recursive: true });

const EMAIL = process.env.DEMO_EMAIL || "sitedemo@example.com";
const PASSWORD = "demo-password-123";

const browser = await chromium.launch({ channel: "msedge" });

async function session(theme, width, height, scale) {
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: scale });
  await ctx.addInitScript((t) => {
    try {
      localStorage.setItem("personal_cloud_theme", t);
    } catch (e) {}
  }, theme);
  const page = await ctx.newPage();
  await page.goto(base + "/login");
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.keyboard.press("Enter");
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 20000 });
  return { ctx, page };
}

async function shot(page, route, name, wait = 2500) {
  await page.goto(base + route);
  await page.waitForTimeout(wait);
  await page.screenshot({ path: `${out}/${name}.png` });
  console.log("wrote", name);
}

// desktop, black on white (the two retro themes are the app's signature look)
{
  const { ctx, page } = await session("retro-paper", 1000, 640, 2);
  await shot(page, "/photos", "photos-paper", 4500);
  await page.goto(base + "/files");
  await page.getByText("Documents", { exact: true }).first().click();
  await page.waitForTimeout(2000);
  await page.setViewportSize({ width: 1440, height: 560 });
  await page.screenshot({ path: `${out}/files-paper.png` });
  console.log("wrote files-paper");
  await page.setViewportSize({ width: 1440, height: 520 });
  await shot(page, "/shares", "shares-paper");
  await ctx.close();
}
// desktop, white on black
{
  const { ctx, page } = await session("retro", 1000, 640, 2);
  await shot(page, "/photos", "photos-ink", 4500);
  await ctx.close();
}
// the ordinary light theme once, to show it is a normal app for normal people
{
  const { ctx, page } = await session("light", 1440, 900, 2);
  await shot(page, "/photos", "photos-light", 4500);
  await ctx.close();
}
// phone width
{
  const { ctx, page } = await session("retro-paper", 390, 844, 3);
  await shot(page, "/photos", "photos-phone", 4500);
  await ctx.close();
}
{
  const { ctx, page } = await session("retro", 390, 844, 3);
  await shot(page, "/photos", "photos-phone-ink", 4500);
  await ctx.close();
}

await browser.close();
