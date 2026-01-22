const scrapeService = require('../services/scrapeService');
const aiService = require('../services/aiService');

// Maximum allowed prompt length to prevent abuse
const MAX_PROMPT_LENGTH = 500;

// Patterns that might indicate prompt injection attempts
const SUSPICIOUS_PATTERNS = [
  /ignore\s+(all\s+)?previous/i,
  /disregard\s+(all\s+)?previous/i,
  /forget\s+(all\s+)?previous/i,
  /override\s+instructions/i,
  /system\s*prompt/i,
  /you\s+are\s+now/i,
  /act\s+as\s+(if\s+you\s+are\s+)?a/i,
  /pretend\s+(to\s+be|you\s+are)/i,
];

/**
 * Sanitize user-provided prompt to prevent injection attacks
 */
function sanitizePrompt(prompt) {
  if (!prompt) return null;

  // Trim and limit length
  let sanitized = String(prompt).trim().slice(0, MAX_PROMPT_LENGTH);

  // Check for suspicious patterns
  for (const pattern of SUSPICIOUS_PATTERNS) {
    if (pattern.test(sanitized)) {
      console.warn(`Suspicious prompt pattern detected and blocked: ${pattern}`);
      return null; // Return null to use default prompt instead
    }
  }

  return sanitized;
}

class AnalyzerController {
  async analyzeUrl(req, res) {
    try {
      console.log('Received request body:', JSON.stringify(req.body, null, 2));

      const { url, model, prompt } = req.body;

      if (!url) {
        return res.status(400).json({ error: 'URL is required' });
      }

      // Sanitize user-provided prompt
      const sanitizedPrompt = sanitizePrompt(prompt);

      // Scrape the URL
      const scrapedContent = await scrapeService.scrapeUrl(url);

      console.log("scrapedContent", scrapedContent);

      // Get AI summary using optional model and sanitized prompt
      const summary = await aiService.summarizeContent(scrapedContent, model, sanitizedPrompt);

      res.json({
        url: url,
        model: model || "claude-3-haiku-20240307",
        title: scrapedContent.title,
        description: scrapedContent.description || scrapedContent.ogDescription || scrapedContent.twitterDescription,
        favicon: scrapedContent.favicon,
        mainImage: scrapedContent.mainImage || scrapedContent.ogImage || scrapedContent.twitterImage,
        summary: summary
      });
    } catch (error) {
      // Log detailed error server-side only
      console.error('Analysis error:', error.message);
      console.error('Full error:', error);

      // Return generic error to client (no internal details)
      res.status(500).json({ error: 'Failed to analyze URL' });
    }
  }
}

module.exports = new AnalyzerController();
