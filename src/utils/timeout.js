/**
 * Timeout utilities for managing async operations with time limits
 */

/**
 * Custom timeout error class
 */
class TimeoutError extends Error {
  constructor(operation, timeoutMs) {
    super(`Operation '${operation}' timed out after ${timeoutMs}ms`);
    this.name = 'TimeoutError';
    this.timeout = timeoutMs;
    this.operation = operation;
    this.isTimeout = true;
  }
}

/**
 * Wraps a promise with a timeout and optional cleanup function
 *
 * @param {Promise} promise - The promise to wrap
 * @param {number} timeoutMs - Timeout in milliseconds
 * @param {string} errorMessage - Error message/operation name for timeout error
 * @param {Function} cleanupFn - Optional async cleanup function called on timeout
 * @returns {Promise} Promise that resolves/rejects with the original promise or times out
 */
async function withTimeout(promise, timeoutMs, errorMessage, cleanupFn = null) {
  let timeoutHandle;

  const timeoutPromise = new Promise((_, reject) => {
    timeoutHandle = setTimeout(async () => {
      // Call cleanup function if provided
      if (cleanupFn) {
        try {
          await cleanupFn();
        } catch (cleanupError) {
          console.error(`Cleanup error for ${errorMessage}:`, cleanupError);
        }
      }

      reject(new TimeoutError(errorMessage, timeoutMs));
    }, timeoutMs);
  });

  try {
    const result = await Promise.race([promise, timeoutPromise]);
    clearTimeout(timeoutHandle);
    return result;
  } catch (error) {
    clearTimeout(timeoutHandle);
    throw error;
  }
}

/**
 * Aggressively closes a Puppeteer browser instance with force-kill fallback
 *
 * @param {Object} browser - Puppeteer browser instance
 * @param {number} timeoutMs - Timeout for graceful close in milliseconds
 */
async function forceBrowserClose(browser, timeoutMs = 5000) {
  if (!browser) {
    return;
  }

  try {
    // Try graceful close with timeout
    await withTimeout(
      browser.close(),
      timeoutMs,
      'Browser close'
    );
    console.log('Browser closed gracefully');
  } catch (error) {
    console.warn('Graceful browser close failed, attempting force kill:', error.message);

    // Force kill the browser process
    try {
      const process = browser.process();
      if (process && process.pid) {
        process.kill('SIGKILL');
        console.log(`Browser process ${process.pid} force-killed with SIGKILL`);
      }
    } catch (killError) {
      console.error('Failed to force-kill browser process:', killError);
    }
  }
}

/**
 * Wraps an operation with timeout and provides standardized error handling
 *
 * @param {string} operationName - Name of the operation for logging
 * @param {Function} operation - Async function to execute
 * @param {number} timeoutMs - Timeout in milliseconds
 * @param {Function} onTimeout - Optional callback called on timeout
 * @returns {Promise} Result of the operation
 */
async function withOperationTimeout(operationName, operation, timeoutMs, onTimeout = null) {
  console.log(`Starting operation: ${operationName} (timeout: ${timeoutMs}ms)`);

  const startTime = Date.now();

  try {
    const result = await withTimeout(
      operation(),
      timeoutMs,
      operationName,
      onTimeout
    );

    const duration = Date.now() - startTime;
    console.log(`Operation '${operationName}' completed in ${duration}ms`);

    return result;
  } catch (error) {
    const duration = Date.now() - startTime;

    if (error instanceof TimeoutError) {
      console.error(`Operation '${operationName}' timed out after ${duration}ms`);
    } else {
      console.error(`Operation '${operationName}' failed after ${duration}ms:`, error.message);
    }

    throw error;
  }
}

/**
 * Get timeout value from environment or use default
 *
 * @param {string} envKey - Environment variable key
 * @param {number} defaultValue - Default timeout value
 * @returns {number} Timeout in milliseconds
 */
function getTimeoutFromEnv(envKey, defaultValue) {
  const envValue = process.env[envKey];
  if (envValue) {
    const parsed = parseInt(envValue, 10);
    if (!isNaN(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return defaultValue;
}

module.exports = {
  TimeoutError,
  withTimeout,
  forceBrowserClose,
  withOperationTimeout,
  getTimeoutFromEnv
};
