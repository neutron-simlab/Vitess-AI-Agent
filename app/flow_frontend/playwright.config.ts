import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  expect: { timeout: 15000 },
  use: {
    baseURL: "http://127.0.0.1:19601",
    viewport: { width: 1500, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command:
      ".venv/bin/python -m streamlit run tests/flow_browser_app.py --server.port 19601 --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false",
    cwd: "../..",
    url: "http://127.0.0.1:19601/_stcore/health",
    reuseExistingServer: false,
  },
});
