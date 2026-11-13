import {defineConfig} from "@playwright/test";
export default defineConfig({
  testDir:"tests/prodcheck",outputDir:"test-results-prodcheck",workers:1,retries:0,
  use:{baseURL:"http://localhost:8083",browserName:"chromium",viewport:{width:1440,height:900}},
  expect:{timeout:15000}
});
