import {defineConfig} from "@playwright/test";
export default defineConfig({
  testDir:"tests/e2e",
  fullyParallel:false,
  workers:1,
  retries:0,
  timeout:90000,
  expect:{timeout:15000},
  use:{baseURL:process.env.E2E_URL||"http://localhost:8082",browserName:"chromium",viewport:{width:1440,height:900},screenshot:"only-on-failure",trace:"retain-on-failure"},
  reporter:[["list"],["html",{open:"never"}]]
});
