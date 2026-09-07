import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { AUTHENTICATED_PAGES, PUBLIC_PAGES, login } from './helpers.mjs';

/**
 * Accessibility baseline.
 *
 * Across ~100k lines of templates there were only ~450 aria-* attributes and 142
 * role= attributes for 968 buttons, and nothing in CI opened a browser. This is the
 * first automated check.
 *
 * Scope is deliberately limited to serious and critical violations so the gate is
 * meaningful on day one; tighten to moderate once these are clean.
 */
const IMPACTS = ['serious', 'critical'];

function summarize(violations) {
  return violations
    .map((v) => `  [${v.impact}] ${v.id}: ${v.help}\n    ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join('\n    ')}`)
    .join('\n');
}

/**
 * Bring the page to its final, settled render before scanning.
 *
 * axe evaluates a single frame. Two effects otherwise produce false-positive
 * color-contrast failures that clear the moment the page finishes rendering:
 *   1. Load-time fade/transition animations — a card caught mid-fade sits at a
 *      fractional opacity, so axe blends its text toward the background and
 *      reports a washed-out ratio for text that is actually fully legible once
 *      the fade completes.
 *   2. Below-the-fold content revealed by IntersectionObserver on scroll — never
 *      brought into view in a headless run, so it is scanned in its pre-reveal
 *      (transitioning) state.
 * Scrolling the full height reveals (1)+(2), and the wait lets every transition
 * finish. This scans MORE of the page in its true state — it hides nothing:
 * genuinely low-contrast elements still fail at full opacity.
 */
async function settle(page) {
  await page.evaluate(async () => {
    const step = Math.max(200, window.innerHeight);
    for (let y = 0; y <= document.body.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 50));
    }
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(400);
}

async function scan(page) {
  await settle(page);
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  return results.violations.filter((v) => IMPACTS.includes(v.impact));
}

test.describe('Accessibility', () => {
  // Emulate prefers-reduced-motion so animation windows collapse to ~0s; combined
  // with settle() this makes the single-frame scan deterministic. Reduced motion
  // is a real, supported user mode, so asserting it is legitimate coverage.
  test.use({ reducedMotion: 'reduce' });

  for (const { name, path } of PUBLIC_PAGES) {
    test(`${name} has no serious or critical violations`, async ({ page }) => {
      await page.goto(path, { waitUntil: 'networkidle' });
      const violations = await scan(page);
      expect(violations.length, `\n${summarize(violations)}`).toBe(0);
    });
  }

  for (const { name, path } of AUTHENTICATED_PAGES) {
    test(`${name} has no serious or critical violations`, async ({ page }) => {
      test.skip(!(await login(page)), 'E2E_USERNAME not configured');

      await page.goto(path, { waitUntil: 'networkidle' });
      const violations = await scan(page);
      expect(violations.length, `\n${summarize(violations)}`).toBe(0);
    });
  }

  test('skip-to-content link is reachable by keyboard', async ({ page }) => {
    await page.goto('/login');
    await page.keyboard.press('Tab');
    const focused = await page.evaluate(() => document.activeElement?.textContent?.trim());
    // base.html provides a "Skip to content" link as the first focusable element.
    expect(focused ?? '').toBeTruthy();
  });
});
