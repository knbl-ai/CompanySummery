const puppeteer = require('puppeteer');

class ScrapeService {
  async scrapeUrl(url) {
    const options = {
      headless: "new",
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage'
      ]
    };
    
    // Use executable path from env if provided (for Docker)
    if (process.env.PUPPETEER_EXECUTABLE_PATH) {
      options.executablePath = process.env.PUPPETEER_EXECUTABLE_PATH;
    }
    
    const browser = await puppeteer.launch(options);
    
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
          content: document.body.innerText
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
