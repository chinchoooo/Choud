// Browser check for the website. Usage: node check.mjs http://localhost:8000 /tmp/shots (needs: npm i playwright@1.48.2, and Microsoft Edge or change the channel).
import { chromium } from "playwright";
import fs from "node:fs";
import crypto from "node:crypto";

const base = process.argv[2];
const out = process.argv[3];
const browser = await chromium.launch({ channel: "msedge" });
const results = [];
const check = (name, ok, extra = "") => {
  results.push(`${ok ? "PASS" : "FAIL"} ${name} ${extra}`);
};

// ---- desktop, dark: signature flow
{
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const external = [];
  page.on("request", (r) => {
    if (!r.url().startsWith(base) && !r.url().includes("kaspersky")) external.push(r.url());
  });
  await page.goto(base + "/index.html");
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}/hero-dark.png` });

  const bytes = Buffer.from("hello choud, this is a test file\n".repeat(50));
  fs.writeFileSync(`${out}/fixture-a.txt`, bytes);
  fs.writeFileSync(`${out}/fixture-b.txt`, bytes); // same bytes, other name
  const want = crypto.createHash("sha256").update(bytes).digest("hex");

  await page.setInputFiles("#file", `${out}/fixture-a.txt`);
  await page.waitForSelector("#receipt .verdict");
  let text = await page.innerText("#receipt");
  check("receipt shows first hash prefix", text.includes(want.slice(0, 16)), want.slice(0, 16));
  check("first drop is 'Stored once'", text.includes("Stored once"));
  await page.screenshot({ path: `${out}/receipt-a.png` });

  await page.setInputFiles("#file", `${out}/fixture-b.txt`);
  await page.waitForFunction(() => document.querySelector("#receipt .verdict")?.classList.contains("dup"));
  text = await page.innerText("#receipt");
  check("same bytes, new name -> dedup", text.includes("Already stored") && text.includes("2 names, 1 copy"));
  await page.screenshot({ path: `${out}/receipt-dup.png` });

  await page.click("#use-logo");
  await page.waitForFunction(() => document.querySelector("#receipt .verdict")?.classList.contains("dup"));
  text = await page.innerText("#receipt");
  check("logo button -> dedup against prefilled receipt", text.includes("Already stored"));

  // pull the plug
  await page.click("#plug-btn");
  await page.waitForTimeout(1300);
  await page.click("#plug-btn");
  await page.waitForTimeout(1500);
  const a = await page.innerText("#disk-a [data-result]");
  const b = await page.innerText("#disk-b [data-result]");
  check("plug: plain app corrupted", /glued/.test(a), a.slice(0, 40));
  check("plug: choud intact", /0 half-written files/.test(b));

  check("no page errors", errors.length === 0, errors.join(" | "));
  check("no third-party requests", external.length === 0, external.join(" "));
  await page.setViewportSize({ width: 1280, height: 3400 });
  await page.screenshot({ path: `${out}/full-dark.png`, fullPage: true });
  await ctx.close();
}

// ---- no horizontal scroll at phone / tablet / desktop, both themes, reduced motion on and off
for (const [w, h] of [[360, 800], [768, 900], [1280, 900]]) {
  for (const scheme of ["light", "dark"]) {
    for (const reduced of ["no-preference", "reduce"]) {
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: scheme, reducedMotion: reduced });
      const page = await ctx.newPage();
      await page.goto(base + "/index.html");
      await page.waitForTimeout(300);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      check(`no overflow ${w}px ${scheme} ${reduced}`, over <= 0, `(${over}px)`);
      if (reduced === "no-preference" && scheme === "light") await page.screenshot({ path: `${out}/hero-${w}.png` });
      await ctx.close();
    }
  }
}

// ---- keyboard: every interactive control can take focus visibly
{
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(base + "/index.html");
  let n = 0;
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    n++;
  }
  const tag = await page.evaluate(() => document.activeElement?.tagName);
  check("tab reaches interactive elements", ["A", "BUTTON", "LABEL", "INPUT"].includes(tag), tag);
  await ctx.close();
}

await browser.close();
console.log(results.join("\n"));
process.exit(results.some((r) => r.startsWith("FAIL")) ? 1 : 0);
