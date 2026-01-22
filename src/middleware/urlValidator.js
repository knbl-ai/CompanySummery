/**
 * SSRF Protection Middleware
 * Validates URLs to prevent Server-Side Request Forgery attacks
 */

// Private IP ranges that should be blocked
const PRIVATE_IP_PATTERNS = [
  /^127\./,                          // 127.0.0.0/8 (localhost)
  /^10\./,                           // 10.0.0.0/8
  /^172\.(1[6-9]|2[0-9]|3[0-1])\./,  // 172.16.0.0/12
  /^192\.168\./,                     // 192.168.0.0/16
  /^0\./,                            // 0.0.0.0/8
  /^169\.254\./,                     // 169.254.0.0/16 (link-local, cloud metadata)
  /^::1$/,                           // IPv6 localhost
  /^fc00:/i,                         // IPv6 private
  /^fe80:/i,                         // IPv6 link-local
];

// Blocked hostnames
const BLOCKED_HOSTNAMES = [
  'localhost',
  'metadata.google.internal',
  'metadata',
  'kubernetes.default',
  'kubernetes.default.svc',
];

/**
 * Check if a hostname/IP is private or blocked
 */
function isBlockedHost(hostname) {
  const lowerHostname = hostname.toLowerCase();

  // Check against blocked hostnames
  if (BLOCKED_HOSTNAMES.includes(lowerHostname)) {
    return true;
  }

  // Check if it's a blocked hostname pattern
  if (lowerHostname.endsWith('.internal') ||
      lowerHostname.endsWith('.local') ||
      lowerHostname.endsWith('.localhost')) {
    return true;
  }

  // Check against private IP patterns
  for (const pattern of PRIVATE_IP_PATTERNS) {
    if (pattern.test(hostname)) {
      return true;
    }
  }

  return false;
}

/**
 * Validate a URL for SSRF protection
 * Returns { valid: true } or { valid: false, reason: string }
 */
function validateUrl(urlString) {
  try {
    const url = new URL(urlString);

    // Only allow http and https protocols
    if (!['http:', 'https:'].includes(url.protocol)) {
      return {
        valid: false,
        reason: `Protocol '${url.protocol}' is not allowed. Only http and https are permitted.`
      };
    }

    // Check if hostname is blocked
    if (isBlockedHost(url.hostname)) {
      return {
        valid: false,
        reason: 'Access to internal or private resources is not allowed.'
      };
    }

    // Block URLs with authentication info (potential for credential leaking)
    if (url.username || url.password) {
      return {
        valid: false,
        reason: 'URLs with embedded credentials are not allowed.'
      };
    }

    // Check for IP addresses in different formats that might bypass checks
    // Decimal IP format (e.g., http://2130706433 = 127.0.0.1)
    if (/^\d+$/.test(url.hostname)) {
      return {
        valid: false,
        reason: 'Numeric IP addresses are not allowed.'
      };
    }

    // Octal IP format
    if (/^0[0-7]+\./.test(url.hostname)) {
      return {
        valid: false,
        reason: 'Octal IP addresses are not allowed.'
      };
    }

    // Hex IP format
    if (/^0x[0-9a-f]+/i.test(url.hostname)) {
      return {
        valid: false,
        reason: 'Hexadecimal IP addresses are not allowed.'
      };
    }

    return { valid: true };

  } catch (error) {
    return {
      valid: false,
      reason: 'Invalid URL format.'
    };
  }
}

/**
 * Express middleware for URL validation
 * Validates the 'url' field in the request body
 */
function urlValidatorMiddleware(req, res, next) {
  const { url } = req.body;

  // If no URL in body, let the controller handle the missing parameter
  if (!url) {
    return next();
  }

  const validation = validateUrl(url);

  if (!validation.valid) {
    console.warn(`Blocked potentially malicious URL request: ${url}, reason: ${validation.reason}, IP: ${req.ip}`);
    return res.status(400).json({
      error: 'Invalid URL',
      message: validation.reason
    });
  }

  next();
}

module.exports = {
  urlValidatorMiddleware,
  validateUrl,
  isBlockedHost
};
