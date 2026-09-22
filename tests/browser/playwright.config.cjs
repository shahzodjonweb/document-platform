const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({testDir:'.',testMatch:'*.spec.cjs',fullyParallel:false,workers:1,timeout:45000,use:{baseURL:process.env.OPS_ORIGIN||'http://127.0.0.1:8000',channel:process.env.PLAYWRIGHT_CHANNEL||'chrome',headless:true,screenshot:'only-on-failure',trace:'retain-on-failure'},reporter:[['list']]});
