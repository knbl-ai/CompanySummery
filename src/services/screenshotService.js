const puppeteer = require('puppeteer');
const { withTimeout, forceBrowserClose, getTimeoutFromEnv } = require('../utils/timeout');

class ScreenshotService {
  getBrowserOptions() {
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

    return options;
  }

  async captureScreenshot(url, options = {}) {
    // Extract options with defaults
    const {
      fullPage = true,
      format = 'png',
      quality = 90,
      delay = 0,
      viewport = { width: 1920, height: 1080 }
    } = options;

    // Validate format
    if (!['png', 'jpeg', 'webp'].includes(format)) {
      throw new Error('Invalid format. Must be png, jpeg, or webp');
    }

    // Validate quality (only for jpeg and webp)
    if ((format === 'jpeg' || format === 'webp') && (quality < 1 || quality > 100)) {
      throw new Error('Quality must be between 1 and 100');
    }

    // Validate delay
    if (delay < 0 || delay > 30000) {
      throw new Error('Delay must be between 0 and 30000 milliseconds');
    }

    // Get configurable timeouts from environment
    const OVERALL_TIMEOUT = getTimeoutFromEnv('SCREENSHOT_OPERATION_TIMEOUT', 80000);
    const BROWSER_LAUNCH_TIMEOUT = getTimeoutFromEnv('SCREENSHOT_BROWSER_LAUNCH_TIMEOUT', 15000);
    const PAGE_NAVIGATION_TIMEOUT = getTimeoutFromEnv('SCREENSHOT_PAGE_NAVIGATION_TIMEOUT', 30000);
    const SCREENSHOT_CAPTURE_TIMEOUT = getTimeoutFromEnv('SCREENSHOT_CAPTURE_TIMEOUT', 20000);

    // Store browser reference for cleanup on timeout
    let browser = null;

    // Wrap entire operation with overall timeout
    return withTimeout(
      this._captureScreenshotInternal(
        url,
        { fullPage, format, quality, delay, viewport },
        BROWSER_LAUNCH_TIMEOUT,
        PAGE_NAVIGATION_TIMEOUT,
        SCREENSHOT_CAPTURE_TIMEOUT,
        (b) => { browser = b; }
      ),
      OVERALL_TIMEOUT,
      'Screenshot capture operation',
      async () => {
        // Cleanup function called on overall timeout
        console.error('Overall screenshot operation timed out, force-closing browser');
        if (browser) {
          await forceBrowserClose(browser);
        }
      }
    );
  }

  async _captureScreenshotInternal(
    url,
    options,
    browserLaunchTimeout,
    pageNavigationTimeout,
    screenshotCaptureTimeout,
    setBrowser
  ) {
    const { fullPage, format, quality, delay, viewport } = options;

    // Get wait strategy from environment (default: load - waits for all resources)
    const waitStrategy = process.env.SCREENSHOT_WAIT_STRATEGY || 'load';

    // Get configurable post-load delay (default: 2000ms for JS execution)
    const postLoadDelay = parseInt(process.env.SCREENSHOT_POST_LOAD_DELAY || '2000', 10);

    console.log(`Launching browser with ${browserLaunchTimeout}ms timeout...`);

    // Launch browser with timeout
    const browser = await withTimeout(
      puppeteer.launch(this.getBrowserOptions()),
      browserLaunchTimeout,
      'Browser launch'
    );

    // Store browser reference for cleanup
    setBrowser(browser);

    console.log('Browser launched successfully');

    try {
      const page = await browser.newPage();

      // Set viewport
      await page.setViewport(viewport);

      console.log(`Navigating to ${url} with waitUntil: ${waitStrategy} (timeout: ${pageNavigationTimeout}ms)...`);

      // Navigate to URL with appropriate wait strategy
      await withTimeout(
        page.goto(url, {
          waitUntil: waitStrategy,
          timeout: pageNavigationTimeout
        }),
        pageNavigationTimeout,
        'Page navigation'
      );

      console.log('Page loaded successfully');

      // Scroll the page to trigger lazy-loaded content
      console.log('Scrolling page to trigger lazy-loaded content...');
      await this._autoScroll(page).catch(err => {
        console.warn('Auto-scroll completed with warnings:', err.message);
      });

      // Wait for images to load (after scrolling)
      console.log('Waiting for images to load...');
      await this._waitForImages(page).catch(err => {
        console.warn('Image loading wait completed with warnings:', err.message);
      });

      // Post-load delay for JavaScript execution and dynamic content
      const totalDelay = Math.max(delay || 0, postLoadDelay);
      if (totalDelay > 0) {
        const safeDelay = Math.min(totalDelay, 10000);
        console.log(`Waiting ${safeDelay}ms for dynamic content and JS execution...`);
        await new Promise(resolve => setTimeout(resolve, safeDelay));
      }

      // Capture screenshot with timeout
      const screenshotOptions = {
        fullPage,
        type: format
      };

      // Add quality for jpeg and webp
      if (format === 'jpeg' || format === 'webp') {
        screenshotOptions.quality = quality;
      }

      console.log(`Capturing screenshot (timeout: ${screenshotCaptureTimeout}ms)...`);

      const buffer = await withTimeout(
        page.screenshot(screenshotOptions),
        screenshotCaptureTimeout,
        'Screenshot capture'
      );

      console.log(`Screenshot captured successfully (${buffer.length} bytes)`);

      // Graceful close with force-kill fallback
      await forceBrowserClose(browser, 3000);

      return buffer;
    } catch (error) {
      console.error('Screenshot capture error:', error.message);

      // Aggressive cleanup on error
      await forceBrowserClose(browser, 3000);

      throw error;
    }
  }

  /**
   * Auto-scroll the page to trigger lazy-loaded content
   * @param {Object} page - Puppeteer page object
   */
  async _autoScroll(page) {
    try {
      await page.evaluate(async () => {
        await new Promise((resolve) => {
          let totalHeight = 0;
          const distance = 100; // Scroll 100px at a time
          const delay = 100; // Wait 100ms between scrolls

          const timer = setInterval(() => {
            const scrollHeight = document.body.scrollHeight;
            window.scrollBy(0, distance);
            totalHeight += distance;

            // Stop when we've scrolled to the bottom
            if (totalHeight >= scrollHeight - window.innerHeight) {
              clearInterval(timer);
              // Scroll back to top
              window.scrollTo(0, 0);
              resolve();
            }
          }, delay);
        });
      });

      console.log('Page auto-scroll completed');
    } catch (error) {
      console.warn('Error during auto-scroll:', error.message);
      throw error;
    }
  }

  /**
   * Wait for images to load on the page
   * @param {Object} page - Puppeteer page object
   * @param {number} timeout - Timeout in milliseconds
   */
  async _waitForImages(page, timeout = 5000) {
    try {
      await page.evaluate(async () => {
        const images = Array.from(document.querySelectorAll('img'));

        await Promise.all(
          images.map(img => {
            if (img.complete) return Promise.resolve();

            return new Promise((resolve, reject) => {
              img.addEventListener('load', resolve);
              img.addEventListener('error', resolve); // Resolve even on error to not block

              // Timeout for individual image
              setTimeout(resolve, 3000);
            });
          })
        );
      });

      console.log('All images loaded successfully');
    } catch (error) {
      console.warn('Error waiting for images:', error.message);
      throw error;
    }
  }
}

module.exports = new ScreenshotService();
