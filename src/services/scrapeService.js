const puppeteer = require('puppeteer');

class ScrapeService {
  async scrapeUrl(url) {
    const browser = await puppeteer.launch({
      headless: "new",
      executablePath: '/usr/bin/chromium',
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage'
      ]
    });
    
    try {
      const page = await browser.newPage();
      await page.goto(url, { 
        waitUntil: 'networkidle0',
        timeout: 30000 
      });

      // Extract text content from the page
      const content = await page.evaluate(() => {
        // Remove script and style elements
        const scripts = document.getElementsByTagName('script');
        const styles = document.getElementsByTagName('style');
        Array.from(scripts).forEach(script => script.remove());
        Array.from(styles).forEach(style => style.remove());

        // Get text content
        return {
          title: document.title,
          text: document.body.innerText
        };
      });

      await browser.close();
      return content;
    } catch (error) {
      await browser.close();
      throw error;
    }
  }
}

module.exports = new ScrapeService();
