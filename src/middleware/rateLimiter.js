const rateLimit = require('express-rate-limit');

// Rate limiter configuration: 100 requests per 15 minutes per IP
const rateLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100, // Limit each IP to 100 requests per windowMs
  message: {
    error: 'Too many requests',
    message: 'You have exceeded the rate limit. Please try again later.',
    retryAfter: '15 minutes'
  },
  standardHeaders: true, // Return rate limit info in the `RateLimit-*` headers
  legacyHeaders: false, // Disable the `X-RateLimit-*` headers
  // Skip rate limiting for certain paths if needed
  skip: (req) => {
    // Could add health check endpoints here
    return false;
  },
  // Use default key generator (handles IPv6 properly)
  // Handler when rate limit is exceeded
  handler: (req, res, next, options) => {
    console.warn(`Rate limit exceeded for IP: ${req.ip}`);
    res.status(429).json(options.message);
  },
  // Validate configuration
  validate: {
    xForwardedForHeader: false // Disable X-Forwarded-For validation warning for Cloud Run
  }
});

module.exports = rateLimiter;
