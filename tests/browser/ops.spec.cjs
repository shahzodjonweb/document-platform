const {test,expect}=require('@playwright/test');
const path=require('path');
test('separate staff login and responsive multilingual reports',async({page})=>{
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto('/ops/login');
 await page.getByRole('button',{name:'Open local staff workspace'}).click();
 await expect(page).toHaveURL(/overview\?environment=development/);
 for(const locale of ['en','uz','ru']){
  for(const width of [1440,390]){
   await page.setViewportSize({width,height:1000});
   await page.goto(`/ops/overview?environment=development&lang=${locale}`);
   await expect(page.locator('html')).toHaveAttribute('lang',locale);
   await expect(page.locator('h1')).toBeVisible();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
   await page.screenshot({path:path.resolve(`docs/design/admin/overview-${locale}-${width}.png`),fullPage:true});
  }
 }
 await page.goto('/ops/users?environment=development&lang=en');
 await expect(page.getByRole('heading',{name:'Users',exact:true})).toBeVisible();
 await page.goto('/ops/plans?lang=en');
 await expect(page.getByText('Draft staging configuration',{exact:false})).toBeVisible();
 await page.goto('/ops/analytics/revenue?lang=en');
 await expect(page.getByRole('heading',{name:'Payments are not enabled'})).toBeVisible();
 expect(errors).toEqual([]);
});
