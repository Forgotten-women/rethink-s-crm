#!/usr/bin/env node

/**
 * Playwright Automation to extract Giving Levels from Madinah campaigns (madinah.com).
 *
 * Prompts in the terminal for campaign URL(s) or takes them as CLI arguments,
 * ensures GBP currency is selected, extracts giving levels (Title, GBP Amount, Description)
 * directly from the donation buttons and cards, prints the extracted items in the terminal,
 * and appends them to a CSV file formatted as a single line per row for direct Excel compatibility.
 */

const { chromium } = require('playwright');
const readline = require('readline');
const fs = require('fs');
const path = require('path');

const CSV_FILE = path.resolve(__dirname, '../giving_levels.csv');

/**
 * Normalizes text to a single clean line without newlines (\n, \r) or tabs (\t)
 * so it can be pasted directly into Excel spreadsheets without creating split rows.
 */
function sanitizeOneLine(val) {
  if (val === null || val === undefined) return '';
  return String(val)
    .replace(/[\r\n\t]+/g, ' ')   // replace newlines & tabs with a space
    .replace(/\s{2,}/g, ' ')       // collapse multiple consecutive spaces
    .trim();
}

/**
 * Escapes fields according to standard CSV RFC 4180 rules, guaranteed single-line.
 */
function escapeCSV(val) {
  const clean = sanitizeOneLine(val);
  return `"${clean.replace(/"/g, '""')}"`;
}

/**
 * Ensures the CSV header exists if the file is new or empty.
 */
function ensureCSVHeader() {
  if (!fs.existsSync(CSV_FILE) || fs.statSync(CSV_FILE).size === 0) {
    const header = 'URL,Title,Amount,Description,ExtractedAt\n';
    fs.writeFileSync(CSV_FILE, header, 'utf8');
  }
}

/**
 * Appends extracted levels to the CSV file.
 */
function appendToCSV(url, levels) {
  ensureCSVHeader();
  const timestamp = new Date().toISOString();
  let content = '';

  for (const item of levels) {
    content += [
      escapeCSV(url),
      escapeCSV(item.title),
      escapeCSV(item.amount),
      escapeCSV(item.description),
      escapeCSV(timestamp),
    ].join(',') + '\n';
  }

  fs.appendFileSync(CSV_FILE, content, 'utf8');
}

/**
 * Extracts giving levels in GBP (£) from a Madinah campaign URL using Playwright.
 */
async function scrapeGivingLevels(url, browser) {
  const context = await browser.newContext({
    userAgent:
      'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    viewport: { width: 1920, height: 1080 },
    locale: 'en-GB',
    timezoneId: 'Europe/London',
  });

  // Mask automated browser signature to pass Vercel checkpoint
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  });

  const page = await context.newPage();

  console.log(`\n🌐 Navigating to: ${url}`);
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  } catch (err) {
    console.warn(`⚠️ Navigation warning: ${err.message}`);
  }

  // Handle Vercel Security Checkpoint if triggered
  console.log('⏳ Checking security checkpoint...');
  for (let i = 0; i < 20; i++) {
    const title = await page.title();
    if (!title.includes('Vercel Security Checkpoint')) {
      break;
    }
    await page.waitForTimeout(1000);
  }

  // Allow dynamic elements / client-side components to load
  console.log('⏳ Waiting for giving level cards to load...');
  try {
    await page.waitForSelector('section button', { timeout: 6000 });
  } catch (err) {
    // Expected on pages with no preset giving level buttons
  }
  await page.waitForTimeout(1000);

  // Verify whether the page is displaying in GBP (£)
  const isGBP = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => /donate\s+[£$€]/i.test(b.innerText));
    return btn ? btn.innerText.includes('£') : false;
  });

  // If not GBP, switch currency to GBP
  if (!isGBP) {
    console.log('💱 Switching currency to GBP (£)...');
    try {
      const input = await page.$('input[id*="currency"]');
      if (input) {
        await input.click();
        await input.fill('GBP');
        await page.waitForTimeout(500);
        const gbpOption = await page.$('[role="option"]:has-text("GBP"), .MuiAutocomplete-option:has-text("GBP")');
        if (gbpOption) {
          await gbpOption.click();
          await page.waitForTimeout(1500);
        }
      }
    } catch (e) {
      console.warn('⚠️ Could not switch currency to GBP:', e.message);
    }
  }

  // Expand all description "Show more" toggles via JavaScript
  await page.evaluate(() => {
    document.querySelectorAll('.show-more-less-clickable').forEach(el => {
      try { el.click(); } catch(e) {}
    });
  });
  await page.waitForTimeout(500);

  // Extract from DOM
  const levels = await page.evaluate(() => {
    // Find all donation buttons
    const donateButtons = Array.from(document.querySelectorAll('button')).filter(b => 
      /donate\s+[£$€]\d+/i.test(b.innerText.trim())
    );

    const results = [];
    const seen = new Set();

    for (const btn of donateButtons) {
      const section = btn.closest('section');
      if (!section) continue;

      // Extract amount directly from the Donate button text
      const btnText = btn.innerText.trim();
      const amtMatch = btnText.match(/donate\s+([£$€]\d[\d,]*(?:\.\d{2})?)/i);
      let amount = amtMatch ? amtMatch[1] : '';

      // Fallback: look for amount element inside section
      if (!amount) {
        const amtEl = section.querySelector('p[class*="mui-1x8e6r9"]');
        if (amtEl) amount = amtEl.innerText.trim();
      }

      // Extract title
      let title = '';
      const titleEl = section.querySelector('p[line="2"], p[class*="mui-2ts54b"]') || section.querySelector('p');
      if (titleEl) {
        title = titleEl.innerText.trim();
      }

      // Extract description
      let description = '';
      const pDesc = section.querySelector('p.mui-11zgg2d, p[class*="mui-11zgg2d"]');
      if (pDesc) {
        description = pDesc.innerText.trim();
      } else {
        const allP = Array.from(section.querySelectorAll('p')).map(p => p.innerText.trim());
        const descCandidates = allP.filter(pText => {
          if (!pText) return false;
          if (pText === title) return false;
          if (/^[£$€]\d+/.test(pText)) return false;
          if (/\bclaimed\b/i.test(pText)) return false;
          if (/^donate\b/i.test(pText)) return false;
          return true;
        });

        if (descCandidates.length > 0) {
          description = descCandidates.join(' ');
        } else {
          const descContainer = section.querySelector('div[class*="mui-"] > span');
          if (descContainer) {
            const clone = descContainer.cloneNode(true);
            clone.querySelectorAll('span[style*="hidden"], .show-more-less-clickable').forEach(el => el.remove());
            description = clone.innerText.trim();
          }
        }
      }

      description = description
        .replace(/\s*\.\.\.\s*Show\s*more\s*$/i, '')
        .replace(/\s*Show\s*(more|less)\s*$/i, '')
        .trim();

      const cleanTitle = title.replace(/[\r\n\t]+/g, ' ').replace(/\s{2,}/g, ' ').trim();
      const cleanDesc = description.replace(/[\r\n\t]+/g, ' ').replace(/\s{2,}/g, ' ').trim();
      const cleanAmount = amount.replace(/[\r\n\t]+/g, '').trim();

      if (!cleanTitle && !cleanAmount) continue;

      const dedupKey = `${cleanTitle}|${cleanAmount}`;
      if (!seen.has(dedupKey)) {
        seen.add(dedupKey);
        results.push({
          title: cleanTitle,
          amount: cleanAmount,
          description: cleanDesc,
        });
      }
    }

    return results;
  });

  await context.close();
  return levels;
}

/**
 * Pretty prints results to the terminal.
 */
function displayResults(url, levels) {
  console.log('\n' + '='.repeat(70));
  console.log(`📌 Results for URL: ${url}`);
  console.log(`📊 Found ${levels.length} Giving Level(s):`);
  console.log('='.repeat(70));

  if (levels.length === 0) {
    console.log('⚠️ No giving levels found on this page.');
    return;
  }

  levels.forEach((lvl, idx) => {
    console.log(`\n[${idx + 1}] Title:       ${lvl.title}`);
    console.log(`    Amount:      ${lvl.amount || 'N/A'}`);
    console.log(`    Description: ${lvl.description || 'N/A'}`);
  });
  console.log('\n' + '-'.repeat(70));
}

/**
 * Reads existing URLs already present in CSV to avoid duplicate scraping.
 */
function getExistingURLs() {
  if (!fs.existsSync(CSV_FILE)) return new Set();
  const content = fs.readFileSync(CSV_FILE, 'utf8');
  const urls = new Set();
  const lines = content.split('\n');
  for (const line of lines) {
    if (!line.trim() || line.startsWith('URL,')) continue;
    const match = line.match(/^"([^"]+)"/) || line.match(/^([^,]+)/);
    if (match) urls.add(match[1].trim());
  }
  return urls;
}

/**
 * Loops through a list of URLs, extracting giving levels and appending to CSV.
 */
async function processBatch(urls, browser, { skipExisting = true } = {}) {
  const existing = skipExisting ? getExistingURLs() : new Set();
  const total = urls.length;
  let processed = 0;
  let skipped = 0;
  let totalExtracted = 0;

  console.log(`\n🚀 Starting batch processing of ${total} campaign URL(s)...`);
  if (skipExisting && existing.size > 0) {
    console.log(`ℹ️ Found ${existing.size} existing URL(s) in CSV. Already scraped URLs will be skipped.`);
  }

  for (let i = 0; i < urls.length; i++) {
    const url = urls[i];
    const indexStr = `[${i + 1}/${total}]`;

    if (skipExisting && existing.has(url)) {
      console.log(`\n${indexStr} ⏭️ Skipping already scraped URL: ${url}`);
      skipped++;
      continue;
    }

    console.log(`\n${'='.repeat(70)}`);
    console.log(`${indexStr} Processing: ${url}`);
    console.log(`${'='.repeat(70)}`);

    try {
      const levels = await scrapeGivingLevels(url, browser);
      displayResults(url, levels);
      if (levels.length > 0) {
        appendToCSV(url, levels);
        console.log(`✅ Appended ${levels.length} item(s) to ${CSV_FILE}`);
        totalExtracted += levels.length;
      } else {
        console.log(`ℹ️ 0 giving levels found for ${url} (no rows appended).`);
      }
      existing.add(url);
      processed++;
    } catch (err) {
      console.error(`❌ Error scraping ${url}: ${err.message}`);
    }

    // Polite pause between requests
    await new Promise(r => setTimeout(r, 500));
  }

  console.log(`\n${'='.repeat(70)}`);
  console.log(`🎉 Batch finished! Processed: ${processed}, Skipped: ${skipped}, Total Giving Levels Appended: ${totalExtracted}`);
  console.log(`📁 File updated: ${CSV_FILE}`);
  console.log(`${'='.repeat(70)}\n`);
}

/**
 * Main interactive CLI loop.
 */
async function main() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  const ask = question => new Promise(resolve => rl.question(question, resolve));

  // Check if a URL or filename was passed via CLI arguments
  const inputArg = process.argv[2];

  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-blink-features=AutomationControlled',
      ],
    });

    if (inputArg) {
      const target = inputArg.trim();

      // Case 1: Argument is a file path
      if (fs.existsSync(target) && fs.statSync(target).isFile()) {
        const fileContent = fs.readFileSync(target, 'utf8');
        const urls = fileContent
          .split('\n')
          .map(l => l.trim())
          .filter(l => l && !l.startsWith('#') && (l.startsWith('http://') || l.startsWith('https://')));

        console.log(`📄 Loaded ${urls.length} URL(s) from ${target}`);
        await processBatch(urls, browser);
      }
      // Case 2: Argument is a single URL
      else if (target.startsWith('http://') || target.startsWith('https://')) {
        const levels = await scrapeGivingLevels(target, browser);
        displayResults(target, levels);
        if (levels.length > 0) {
          appendToCSV(target, levels);
          console.log(`✅ Appended ${levels.length} items to CSV: ${CSV_FILE}`);
        }
      } else {
        console.error(`❌ Invalid argument: "${target}". Provide a valid URL or path to a links file.`);
      }
    } else {
      console.log('\n======================================================');
      console.log('   Madinah Campaign Giving Levels Scraper (Playwright)');
      console.log('======================================================');
      console.log(`Destination CSV: ${CSV_FILE}\n`);

      while (true) {
        const answer = await ask('Enter Campaign URL or Links File (e.g. links.txt, or "exit" to quit): ');
        const trimmed = answer.trim();

        if (!trimmed || trimmed.toLowerCase() === 'exit' || trimmed.toLowerCase() === 'q') {
          console.log('\nExiting scraper. Goodbye!');
          break;
        }

        // Case 1: Path to a file
        if (fs.existsSync(trimmed) && fs.statSync(trimmed).isFile()) {
          const fileContent = fs.readFileSync(trimmed, 'utf8');
          const urls = fileContent
            .split('\n')
            .map(l => l.trim())
            .filter(l => l && !l.startsWith('#') && (l.startsWith('http://') || l.startsWith('https://')));

          console.log(`📄 Loaded ${urls.length} URL(s) from ${trimmed}`);
          await processBatch(urls, browser);
          break;
        }
        // Case 2: Single URL
        else if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
          try {
            const levels = await scrapeGivingLevels(trimmed, browser);
            displayResults(trimmed, levels);
            if (levels.length > 0) {
              appendToCSV(trimmed, levels);
              console.log(`✅ Appended ${levels.length} row(s) to ${CSV_FILE}\n`);
            }
          } catch (err) {
            console.error(`❌ Error scraping ${trimmed}:`, err.message);
          }
        } else {
          console.log('❌ Invalid input. Please enter a full URL (http/https) or valid path to a text file.\n');
        }
      }
    }
  } catch (err) {
    console.error('❌ Failed to run scraper:', err);
  } finally {
    if (browser) await browser.close();
    rl.close();
  }
}

main();
