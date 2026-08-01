// @sparticuz/chromium ships as native ESM (no CJS build) - this file must be ESM too, since
// Node's Lambda runtime does not support require()-ing an ESM-only package from CommonJS.
import playwrightExtra from "playwright-extra";
import stealthPlugin from "puppeteer-extra-plugin-stealth";
import sparticuzChromium from "@sparticuz/chromium";

const { chromium } = playwrightExtra;
chromium.use(stealthPlugin());

const DEFAULT_WAIT_MS = 8000;
const GOTO_TIMEOUT_MS = 30000;
const VIEWPORT = { width: 1280, height: 800 };
// A real desktop Chrome UA, not the headless-labeled default - paired with the stealth plugin's
// navigator.webdriver/chrome.runtime patches, this is the "basic effort" anti-bot layer (see the plan:
// no proxy rotation, no CAPTCHA solving - that tier stays on Zyte).
const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

export const handler = async (event) => {
  const url = event && event.url;
  if (!url) {
    throw new Error("event.url is required");
  }
  const waitMs = (event && event.waitMs) || DEFAULT_WAIT_MS;

  const browser = await chromium.launch({
    args: [...sparticuzChromium.args, "--disable-blink-features=AutomationControlled"],
    executablePath: await sparticuzChromium.executablePath(),
    headless: true,
  });

  try {
    const context = await browser.newContext({
      userAgent: USER_AGENT,
      viewport: VIEWPORT,
      locale: "en-US",
      extraHTTPHeaders: { "Accept-Language": "en-US,en;q=0.9" },
    });
    const page = await context.newPage();
    // networkidle hangs indefinitely on pages with persistent background polling (e.g. ASML) -
    // domcontentloaded plus a fixed wait (same strategy Zyte's own waitForTimeout action uses) is more robust.
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: GOTO_TIMEOUT_MS });
    await page.waitForTimeout(waitMs);
    const html = await page.content();
    return { html };
  } finally {
    await browser.close();
  }
};
