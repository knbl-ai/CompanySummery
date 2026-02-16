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
    const SCREENSHOT_GCS_UPLOAD_TIMEOUT = getTimeoutFromEnv('SCREENSHOT_GCS_UPLOAD_TIMEOUT', 15000);

    console.log('Configured timeouts (ms):', {
      OVERALL: OVERALL_TIMEOUT,
      BROWSER_LAUNCH: BROWSER_LAUNCH_TIMEOUT,
      PAGE_NAVIGATION: PAGE_NAVIGATION_TIMEOUT,
      SCREENSHOT_CAPTURE: SCREENSHOT_CAPTURE_TIMEOUT,
      GCS_UPLOAD: SCREENSHOT_GCS_UPLOAD_TIMEOUT
    });

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
      const memoryBefore = process.memoryUsage();
      console.log(`Memory before page creation: RSS=${Math.round(memoryBefore.rss / 1024 / 1024)}MB, Heap=${Math.round(memoryBefore.heapUsed / 1024 / 1024)}MB`);

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

      const memoryAfter = process.memoryUsage();
      console.log(`Memory after screenshot: RSS=${Math.round(memoryAfter.rss / 1024 / 1024)}MB, Heap=${Math.round(memoryAfter.heapUsed / 1024 / 1024)}MB`);

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
    console.log('Starting page auto-scroll...');
    try {
      await page.evaluate(async () => {
        await new Promise((resolve) => {
          let totalHeight = 0;
          const distance = 100;
          const delay = 50; // Faster scroll
          const maxHeight = 15000; // Cap at 15k pixels to prevent infinite loops
          const scrollTimeout = 40000; // 40s max for scrolling
          const startTime = Date.now();

          const timer = setInterval(() => {
            const scrollHeight = document.body.scrollHeight;
            window.scrollBy(0, distance);
            totalHeight += distance;

            const timeElapsed = Date.now() - startTime;

            // Stop when we've scrolled to the bottom, reached max height, or timed out
            if (totalHeight >= scrollHeight - window.innerHeight || totalHeight >= maxHeight || timeElapsed >= scrollTimeout) {
              clearInterval(timer);
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
