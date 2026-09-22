const { test, expect } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;
test('extended staff surfaces remain readable in both themes', async ({ page }) => {
 test.setTimeout(120000);
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.goto('/ops/login');
 await page.getByRole('button', { name: 'Open local staff workspace' }).click();
 const issues=[];
 await page.setViewportSize({ width: 390, height: 1000 });
 for (const theme of ['light', 'dark']) {
  for (const route of ['overview', 'integrations', 'staff', 'payments', 'analytics/revenue']) {
   await page.goto(`/ops/${route}?lang=en&environment=development`);
   await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
   const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
   if(result.violations.length) issues.push({theme,route,violations:result.violations.map(v => ({id:v.id,nodes:v.nodes.map(n => ({target:n.target,details:n.failureSummary}))}))});
   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${theme}/${route} overflow`).toBe(true);
  }
 }
 require('fs').writeFileSync('.private/admin-accessibility.json',JSON.stringify(issues,null,2));
 expect(issues.map(({theme,route,violations})=>({theme,route,rules:violations.map(v=>v.id)}))).toEqual([]);
});
