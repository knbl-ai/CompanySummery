const { getTimeoutFromEnv } = require('../utils/timeout');

/**
 * Express middleware to enforce request timeout
 *
 * @param {number} timeoutMs - Timeout in milliseconds (optional, defaults to env or 90000ms)
 * @returns {Function} Express middleware function
 */
function timeoutMiddleware(timeoutMs = null) {
  const timeout = timeoutMs || getTimeoutFromEnv('SCREENSHOT_REQUEST_TIMEOUT', 90000);

  return (req, res, next) => {
    // Set timeout handler
    const timeoutHandle = setTimeout(() => {
      // Only send response if headers haven't been sent yet
      if (!res.headersSent) {
        console.error(`Request timeout: ${req.method} ${req.path} exceeded ${timeout}ms`);

        res.status(504).json({
          error: 'Request timeout',
          details: `Operation exceeded ${timeout}ms timeout`,
          timeout: true,
          path: req.path,
          method: req.method
        });
      }
    }, timeout);

    // Clear timeout when response finishes
    res.on('finish', () => {
      clearTimeout(timeoutHandle);
    });

    // Clear timeout if connection closes
    res.on('close', () => {
      clearTimeout(timeoutHandle);
    });

    next();
  };
}

module.exports = timeoutMiddleware;
