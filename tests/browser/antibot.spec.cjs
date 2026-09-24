const { test, expect } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;
const fs = require('fs');
const path = require('path');

test('anti-bot settings are readable, accessible, and keep secrets blank', async ({ page, baseURL }) => {
  test.setTimeout(120000);
  // This uses the explicit local staff fixture and never configures a live service.
  expect(['localhost', '127.0.0.1']).toContain(new URL(baseURL).hostname);
  const output = path.resolve(process.env.ANTIBOT_QA_OUTPUT || '../antibot-review/admin-browser');
  fs.mkdirSync(output, { recursive: true });
  const browserErrors = [];
  const checks = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/ops/login?lang=en');
  await page.getByRole('button', { name: 'Open local staff workspace' }).click();
  await expect(page).toHaveURL(/overview\?environment=development/);
  const headings = { en: 'Anti-bot verification', uz: 'Botlardan himoya', ru: 'Защита от ботов' };

  for (const locale of ['en', 'uz', 'ru']) {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const theme of ['light', 'dark']) {
        await page.goto(`/ops/integrations?lang=${locale}`);
        await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
        await expect(page.locator('html')).toHaveAttribute('lang', locale);
        const card = page.locator('#antibot-settings');
        await expect(card.getByRole('heading', { name: headings[locale], exact: true })).toBeVisible();
        await expect(card.locator('input[name=secret_key]')).toHaveValue('');
        await expect(card.locator('input[name=secret_key]')).toHaveAttribute('type', 'password');
        await expect(card.locator('input[name=secret_key]')).toHaveAttribute('autocomplete', 'new-password');
        for (const input of await page.locator('input[type=password]').all()) {
          await expect(input).toHaveValue('');
        }
        await expect(card.locator('input[type=checkbox][name=web_enabled]')).toBeVisible();
        await expect(card.locator('input[type=checkbox][name=bot_enabled]')).toBeVisible();
        await expect(card.locator('textarea[name=allowed_hostnames]')).toBeVisible();
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
        expect(overflow, `${locale}/${width}/${theme}: horizontal overflow`).toBe(false);
        const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
        const violations = axe.violations.map(v => ({ id: v.id, targets: v.nodes.map(n => n.target) }));
        const screenshot = `antibot-${locale}-${width}-${theme}.png`;
        await card.screenshot({ path: path.join(output, screenshot) });
        checks.push({ locale, width, theme, overflow, secretsBlank: true, violations, screenshot });
      }
    }
  }
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ checks, browserErrors }, null, 2));
  expect(browserErrors).toEqual([]);
  expect(checks.filter(item => item.violations.length)).toEqual([]);
});
