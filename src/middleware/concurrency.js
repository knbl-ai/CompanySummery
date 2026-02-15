const { getTimeoutFromEnv } = require('../utils/timeout');

/**
 * Semaphore-based concurrency limiter
 */
class ConcurrencyLimiter {
  constructor(maxConcurrent) {
    this.maxConcurrent = maxConcurrent;
    this.current = 0;
    this.queue = [];
  }

  /**
   * Acquire a concurrency slot
   * @returns {Promise<void>} Resolves when slot is available
   */
  async acquire() {
    if (this.current < this.maxConcurrent) {
      this.current++;
      console.log(`Concurrency slot acquired (${this.current}/${this.maxConcurrent})`);
      return;
    }

    // Need to wait in queue
    console.log(`Concurrency limit reached (${this.maxConcurrent}), queuing request (queue size: ${this.queue.length + 1})`);

    return new Promise((resolve) => {
      this.queue.push(resolve);
    });
  }

  /**
   * Release a concurrency slot
   */
  release() {
    this.current--;
    console.log(`Concurrency slot released (${this.current}/${this.maxConcurrent})`);

    // Process next in queue if any
    if (this.queue.length > 0) {
      const resolve = this.queue.shift();
      this.current++;
      console.log(`Processing queued request (${this.current}/${this.maxConcurrent}, remaining in queue: ${this.queue.length})`);
      resolve();
    }
  }

  /**
   * Get current status
   * @returns {Object} Status object with current and queued counts
   */
  getStatus() {
    return {
      current: this.current,
      max: this.maxConcurrent,
      queued: this.queue.length
    };
  }
}

/**
 * Express middleware factory for concurrency limiting
 *
 * @param {number} maxConcurrent - Maximum number of concurrent requests (optional, defaults to env or 5)
 * @returns {Function} Express middleware function
 */
function concurrencyMiddleware(maxConcurrent = null) {
  const limit = maxConcurrent || getTimeoutFromEnv('SCREENSHOT_MAX_CONCURRENT', 5);
  const limiter = new ConcurrencyLimiter(limit);

  console.log(`Concurrency limiter initialized with max ${limit} concurrent requests`);

  return async (req, res, next) => {
    // Acquire slot (may queue)
    await limiter.acquire();

    // Release slot when response completes or connection closes (only once)
    let released = false;
    const releaseSlot = () => {
      if (!released) {
        released = true;
        limiter.release();
      }
    };

    res.on('finish', releaseSlot);
    res.on('close', releaseSlot);

    // Add concurrency status to request for debugging
    req.concurrencyStatus = limiter.getStatus();

    next();
  };
}

module.exports = concurrencyMiddleware;
