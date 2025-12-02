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

      // Extract metadata and content from the page
      const data = await page.evaluate(() => {
        // Remove script and style elements for clean text content
        const scripts = document.getElementsByTagName('script');
        const styles = document.getElementsByTagName('style');
        Array.from(scripts).forEach(script => script.remove());
        Array.from(styles).forEach(style => style.remove());

        // Helper function to get meta tag content
        const getMetaContent = (name) => {
          const meta = document.querySelector(`meta[name="${name}"]`) || 
                      document.querySelector(`meta[property="${name}"]`);
          return meta ? meta.content : null;
        };

        // Find the most likely logo
        const findLogo = () => {
          // Check for common logo selectors
          const logoSelectors = [
            'link[rel="icon"]',
            'link[rel="shortcut icon"]',
            'link[rel="apple-touch-icon"]',
            // Look for common logo image patterns
            'img[src*="logo"]',
            'img[alt*="logo"]',
            '.logo img',
            '#logo img'
          ];

          for (const selector of logoSelectors) {
            const element = document.querySelector(selector);
            if (element) {
              return element.href || element.src;
            }
          }
          return null;
        };

        // Find main image
        const findMainImage = () => {
          // First check og:image
          const ogImage = getMetaContent('og:image');
          if (ogImage) return ogImage;

          // Then look for article featured image
          const articleImage = document.querySelector('article img') ||
                             document.querySelector('[class*="featured"] img') ||
                             document.querySelector('[class*="hero"] img');
          
          return articleImage ? articleImage.src : null;
        };

        return {
          // Basic metadata
          title: document.title,
          description: getMetaContent('description'),
          author: getMetaContent('author'),
          
          // Open Graph metadata
          ogTitle: getMetaContent('og:title'),
          ogDescription: getMetaContent('og:description'),
          ogImage: getMetaContent('og:image'),
          ogType: getMetaContent('og:type'),
          
          // Twitter Card metadata
          twitterCard: getMetaContent('twitter:card'),
          twitterTitle: getMetaContent('twitter:title'),
          twitterDescription: getMetaContent('twitter:description'),
          twitterImage: getMetaContent('twitter:image'),
          
          // Visual elements
          logo: findLogo(),
          mainImage: findMainImage(),
          favicon: document.querySelector('link[rel="icon"]')?.href ||
                  document.querySelector('link[rel="shortcut icon"]')?.href,
          
          // Page content
          content: document.body.innerText,
          
          // Additional metadata
          lastModified: document.lastModified || null,
          language: document.documentElement.lang || null,
          canonicalUrl: document.querySelector('link[rel="canonical"]')?.href || null
        };
      });

      await browser.close();
      return data;
    } catch (error) {
      await browser.close();
      throw error;
    }
  }
}

module.exports = new ScrapeService();
