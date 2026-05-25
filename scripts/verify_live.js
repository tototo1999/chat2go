const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

async function run() {
  console.log('Starting automated Playwright verification...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
  });
  
  const page = await context.newPage();
  
  console.log('Navigating to https://chat2go.cn/mcp/ ...');
  await page.goto('https://chat2go.cn/mcp/', { waitUntil: 'networkidle' });
  
  // Wait for dynamic assets and animations to settle
  console.log('Waiting for elements to render...');
  await page.waitForTimeout(4000);
  
  // Ensure the assets folder exists
  const assetsDir = path.join(__dirname, '..', 'mcp', 'assets');
  if (!fs.existsSync(assetsDir)) {
    fs.mkdirSync(assetsDir, { recursive: true });
  }
  
  const screenshotPath = path.join(assetsDir, 'live_verification.png');
  console.log(`Capturing screenshot to ${screenshotPath}...`);
  await page.screenshot({ path: screenshotPath });
  
  await browser.close();
  console.log('Verification completed successfully!');
}

run().catch(err => {
  console.error('Verification failed:', err);
  process.exit(1);
});
