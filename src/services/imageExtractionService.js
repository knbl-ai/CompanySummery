const puppeteer = require('puppeteer');
const { withTimeout, forceBrowserClose, getTimeoutFromEnv } = require('../utils/timeout');

class ImageExtractionService {
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

  async extractImages(url, options = {}) {
    const startTime = Date.now();

    // Extract options with defaults
    const {
      minWidth = parseInt(process.env.IMAGE_MIN_WIDTH || '100', 10),
      minHeight = parseInt(process.env.IMAGE_MIN_HEIGHT || '100', 10),
      classifyImages = true,
      includeBackgrounds = false,
      maxImages = 100
    } = options;

    // Get configurable timeouts from environment
    const OVERALL_TIMEOUT = getTimeoutFromEnv('IMAGE_EXTRACTION_TIMEOUT', 60000);
    const BROWSER_LAUNCH_TIMEOUT = getTimeoutFromEnv('SCREENSHOT_BROWSER_LAUNCH_TIMEOUT', 15000);
    const PAGE_NAVIGATION_TIMEOUT = getTimeoutFromEnv('SCREENSHOT_PAGE_NAVIGATION_TIMEOUT', 30000);

    // Store browser reference for cleanup on timeout
    let browser = null;

    try {
      // Wrap entire operation with overall timeout
      const result = await withTimeout(
        this._extractImagesInternal(
          url,
          { minWidth, minHeight, classifyImages, includeBackgrounds, maxImages },
          BROWSER_LAUNCH_TIMEOUT,
          PAGE_NAVIGATION_TIMEOUT,
          (b) => { browser = b; }
        ),
        OVERALL_TIMEOUT,
        'Image extraction operation',
        async () => {
          // Cleanup function called on overall timeout
          console.error('Overall image extraction operation timed out, force-closing browser');
          if (browser) {
            await forceBrowserClose(browser);
          }
        }
      );

      const processingTime = Date.now() - startTime;

      return {
        images: result.images,
        metadata: {
          processingTime,
          totalImages: result.images.length,
          filteredOut: result.filteredCount,
          lazyLoadedCount: result.lazyLoadedCount
        }
      };

    } catch (error) {
      console.error('Image extraction error:', error.message);
      throw error;
    }
  }

  async _extractImagesInternal(
    url,
    options,
    browserLaunchTimeout,
    pageNavigationTimeout,
    setBrowser
  ) {
    const { minWidth, minHeight, classifyImages, includeBackgrounds, maxImages } = options;

    // Get wait strategy from environment (use load for faster extraction)
    const waitStrategy = process.env.SCREENSHOT_WAIT_STRATEGY || 'load';

    // Use shorter post-load delay for image extraction
    const postLoadDelay = parseInt(process.env.SCREENSHOT_POST_LOAD_DELAY || '2000', 10);

    console.log(`Launching browser for image extraction (timeout: ${browserLaunchTimeout}ms)...`);

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
      await page.setViewport({ width: 1920, height: 1080 });

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
      console.log('Scrolling page to trigger lazy-loaded images...');
      await this._autoScroll(page).catch(err => {
        console.warn('Auto-scroll completed with warnings:', err.message);
      });

      // Wait for images to load (after scrolling)
      console.log('Waiting for images to load...');
      await this._waitForImages(page).catch(err => {
        console.warn('Image loading wait completed with warnings:', err.message);
      });

      // Post-load delay for JavaScript execution and dynamic content
      if (postLoadDelay > 0) {
        const safeDelay = Math.min(postLoadDelay, 10000);
        console.log(`Waiting ${safeDelay}ms for dynamic content...`);
        await new Promise(resolve => setTimeout(resolve, safeDelay));
      }

      // Extract all image data
      console.log('Extracting image data...');
      const imageData = await this._extractImageData(page, includeBackgrounds);

      console.log(`Extracted ${imageData.allImages.length} total images`);

      // Filter images
      const filteredImages = this._filterImages(imageData.allImages, { minWidth, minHeight });

      console.log(`After filtering: ${filteredImages.length} images remain`);

      // Limit to maxImages
      const limitedImages = filteredImages.slice(0, maxImages);

      // Classify images if requested
      let finalImages = limitedImages;
      if (classifyImages) {
        console.log('Classifying images...');
        finalImages = this._classifyImages(limitedImages, imageData.pageContext);
      }

      // Graceful close with force-kill fallback
      await forceBrowserClose(browser, 3000);

      return {
        images: finalImages,
        filteredCount: imageData.allImages.length - filteredImages.length,
        lazyLoadedCount: imageData.lazyLoadedCount
      };

    } catch (error) {
      console.error('Image extraction internal error:', error.message);

      // Aggressive cleanup on error
      await forceBrowserClose(browser, 3000);

      throw error;
    }
  }

  /**
   * Extract all image data from the page
   * @param {Object} page - Puppeteer page object
   * @param {boolean} includeBackgrounds - Whether to include CSS background images
   * @returns {Object} - { allImages: [], pageContext: {}, lazyLoadedCount: 0 }
   */
  async _extractImageData(page, includeBackgrounds = false) {
    const result = await page.evaluate((includeBackgrounds) => {
      const images = [];
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;

      // Extract regular img elements
      const imgElements = Array.from(document.querySelectorAll('img'));

      imgElements.forEach((img, index) => {
        // Get bounding rect for position and visibility
        const rect = img.getBoundingClientRect();

        // Determine if image is in header/nav
        let inHeader = false;
        let parentEl = img.parentElement;
        let depth = 0;
        while (parentEl && depth < 5) {
          const tagName = parentEl.tagName.toLowerCase();
          if (tagName === 'header' || tagName === 'nav') {
            inHeader = true;
            break;
          }
          parentEl = parentEl.parentElement;
          depth++;
        }

        // Check if contains logo-related keywords
        const src = img.src || '';
        const alt = img.alt || '';
        const className = img.className || '';
        const containsLogo =
          src.toLowerCase().includes('logo') ||
          alt.toLowerCase().includes('logo') ||
          className.toLowerCase().includes('logo');

        // Check for product keywords
        const productKeywords = ['product', 'iphone', 'macbook', 'ipad', 'watch', 'airpods', 'laptop', 'phone', 'tablet'];
        const containsProductKeywords = productKeywords.some(keyword =>
          src.toLowerCase().includes(keyword) ||
          alt.toLowerCase().includes(keyword) ||
          className.toLowerCase().includes(keyword)
        );

        // Check if lazy loaded (has data-src or loading attribute)
        const isLazyLoaded =
          img.hasAttribute('data-src') ||
          img.hasAttribute('loading') ||
          img.hasAttribute('data-lazy');

        // Get image format from src
        let format = 'unknown';
        if (src) {
          const ext = src.split('.').pop().split('?')[0].toLowerCase();
          if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(ext)) {
            format = ext === 'jpg' ? 'jpeg' : ext;
          }
        }

        images.push({
          src: src,
          srcset: img.srcset || null,
          alt: alt,
          width: img.naturalWidth || 0,
          height: img.naturalHeight || 0,
          format: format,
          position: {
            x: Math.round(rect.left),
            y: Math.round(rect.top),
            visible: rect.top < viewportHeight && rect.bottom > 0 && rect.left < viewportWidth && rect.right > 0
          },
          containsLogo: containsLogo,
          containsProductKeywords: containsProductKeywords,
          inHeader: inHeader,
          isLazyLoaded: isLazyLoaded,
          className: className,
          parentTag: img.parentElement ? img.parentElement.tagName.toLowerCase() : null
        });
      });

      // Extract CSS background images if requested
      if (includeBackgrounds) {
        const allElements = Array.from(document.querySelectorAll('*'));

        allElements.forEach(el => {
          const style = window.getComputedStyle(el);
          const bgImage = style.backgroundImage;

          if (bgImage && bgImage !== 'none' && bgImage.includes('url(')) {
            const urlMatch = bgImage.match(/url\(['"]?([^'"]+)['"]?\)/);
            if (urlMatch && urlMatch[1]) {
              const url = urlMatch[1];

              // Skip data URIs and very small images
              if (url.startsWith('data:')) return;

              const rect = el.getBoundingClientRect();

              images.push({
                src: url,
                srcset: null,
                alt: '',
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                format: 'background',
                position: {
                  x: Math.round(rect.left),
                  y: Math.round(rect.top),
                  visible: rect.top < viewportHeight && rect.bottom > 0
                },
                containsLogo: false,
                containsProductKeywords: false,
                inHeader: false,
                isLazyLoaded: false,
                className: el.className || '',
                parentTag: 'background'
              });
            }
          }
        });
      }

      // Count lazy loaded images
      const lazyLoadedCount = images.filter(img => img.isLazyLoaded).length;

      return {
        allImages: images,
        pageContext: {
          viewportWidth: viewportWidth,
          viewportHeight: viewportHeight,
          scrollHeight: document.body.scrollHeight
        },
        lazyLoadedCount: lazyLoadedCount
      };
    }, includeBackgrounds);

    return result;
  }

  /**
   * Filter images based on criteria
   * @param {Array} images - Array of image objects
   * @param {Object} options - Filter options
   * @returns {Array} - Filtered images
   */
  _filterImages(images, options) {
    const { minWidth, minHeight } = options;

    return images.filter(img => {
      // Filter by minimum dimensions
      if (img.width < minWidth || img.height < minHeight) {
        return false;
      }

      // Filter out tracking pixels (1x1 images)
      if (img.width === 1 && img.height === 1) {
        return false;
      }

      // Filter out data URIs (base64 images)
      if (img.src && img.src.startsWith('data:')) {
        return false;
      }

      // Filter out empty src
      if (!img.src || img.src === '') {
        return false;
      }

      return true;
    });
  }

  /**
   * Classify images into categories
   * @param {Array} images - Array of image objects
   * @param {Object} pageContext - Page context (viewport size, etc.)
   * @returns {Array} - Images with classification added
   */
  _classifyImages(images, pageContext) {
    const { viewportWidth, viewportHeight } = pageContext;

    return images.map(img => {
      let classification = 'content';

      // Hero image: large, at top, full or near-full width
      if (
        img.position.y < viewportHeight * 0.2 &&
        img.width > viewportWidth * 0.5 &&
        img.height > 400
      ) {
        classification = 'hero';
      }
      // Logo: contains logo keyword, in header, small-medium size
      else if (img.containsLogo && img.inHeader && img.width < 300) {
        classification = 'logo';
      }
      // Product image: medium-large, contains product keywords
      else if (
        img.width >= 300 &&
        img.height >= 200 &&
        img.containsProductKeywords
      ) {
        classification = 'product';
      }
      // Icon: very small
      else if (img.width < 100 && img.height < 100) {
        classification = 'icon';
      }
      // Thumbnail: small-medium, in grid-like structure
      else if (
        img.width >= 100 &&
        img.width < 400 &&
        img.height >= 100 &&
        img.height < 400
      ) {
        classification = 'thumbnail';
      }

      // Return clean image object with classification
      return {
        src: img.src,
        srcset: img.srcset,
        alt: img.alt,
        width: img.width,
        height: img.height,
        format: img.format,
        position: img.position,
        classification: classification,
        isLazyLoaded: img.isLazyLoaded
      };
    });
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

            return new Promise((resolve) => {
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

module.exports = new ImageExtractionService();
