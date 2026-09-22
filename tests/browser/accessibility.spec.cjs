const{test,expect}=require('@playwright/test');
const AxeBuilder=require('@axe-core/playwright').default;
test('staff overview has no automated WCAG 2 A/AA violations',async({page})=>{
 await page.goto('/ops/login');await page.getByRole('button',{name:'Open local staff workspace'}).click();
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:1000});
  const results=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze();
  expect(results.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))).toEqual([]);
 }
});
