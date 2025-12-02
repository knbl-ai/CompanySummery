const imageExtractionService = require('../services/imageExtractionService');
const { TimeoutError } = require('../utils/timeout');

class ImageExtractionController {
  async extractImages(req, res) {
    const startTime = Date.now();

    try {
      const { url, options = {} } = req.body;

      // Validate URL
      if (!url) {
        return res.status(400).json({
          success: false,
          error: 'URL is required',
          details: 'Please provide a valid URL in the request body'
        });
      }

      // Validate URL format
      try {
        new URL(url);
      } catch (error) {
        return res.status(400).json({
          success: false,
          error: 'Invalid URL format',
          details: 'URL must be a valid HTTP or HTTPS URL'
        });
      }

      // Validate options if provided
      if (options.minWidth && (typeof options.minWidth !== 'number' || options.minWidth < 0)) {
        return res.status(400).json({
          success: false,
          error: 'Invalid minWidth',
          details: 'minWidth must be a positive number'
        });
      }

      if (options.minHeight && (typeof options.minHeight !== 'number' || options.minHeight < 0)) {
        return res.status(400).json({
          success: false,
          error: 'Invalid minHeight',
          details: 'minHeight must be a positive number'
        });
      }

      if (options.maxImages && (typeof options.maxImages !== 'number' || options.maxImages < 1)) {
        return res.status(400).json({
          success: false,
          error: 'Invalid maxImages',
          details: 'maxImages must be a positive number'
        });
      }

      console.log(`Extracting images from: ${url}`);
      console.log(`Options:`, JSON.stringify(options));

      // Extract images
      const result = await imageExtractionService.extractImages(url, options);

      const elapsedMs = Date.now() - startTime;

      console.log(`Image extraction completed: ${result.images.length} images in ${elapsedMs}ms`);

      // Return successful response
      res.json({
        success: true,
        url: url,
        totalImages: result.images.length,
        images: result.images,
        metadata: {
          ...result.metadata,
          elapsedMs: elapsedMs
        }
      });

    } catch (error) {
      const elapsedMs = Date.now() - startTime;

      console.error('Image extraction error:', error);

      // Handle timeout errors specifically
      if (error instanceof TimeoutError || error.isTimeout) {
        return res.status(504).json({
          success: false,
          error: 'Image extraction timed out',
          details: error.message,
          timeout: true,
          operation: error.operation || 'Image extraction',
          elapsedMs: elapsedMs,
          retryable: true
        });
      }

      // Handle navigation/page load errors
      if (error.message && error.message.includes('Navigation')) {
        return res.status(500).json({
          success: false,
          error: 'Failed to load page',
          details: error.message,
          elapsedMs: elapsedMs,
          retryable: true
        });
      }

      // Handle browser launch errors
      if (error.message && error.message.includes('Browser')) {
        return res.status(500).json({
          success: false,
          error: 'Failed to launch browser',
          details: error.message,
          elapsedMs: elapsedMs,
          retryable: true
        });
      }

      // Generic error response
      res.status(500).json({
        success: false,
        error: 'Failed to extract images',
        details: error.message || 'An unexpected error occurred',
        elapsedMs: elapsedMs,
        retryable: false
      });
    }
  }
}

module.exports = new ImageExtractionController();
