const screenshotService = require('../services/screenshotService');
const storageService = require('../services/storageService');
const { TimeoutError } = require('../utils/timeout');

class ScreenshotController {
  async captureScreenshot(req, res) {
    const startTime = Date.now();

    try {
      console.log('Screenshot request received:', JSON.stringify(req.body, null, 2));

      const { url, fullPage, format, quality, delay } = req.body;

      // Validate required parameters
      if (!url) {
        return res.status(400).json({
          error: 'URL is required',
          details: 'Request body must include a valid URL'
        });
      }

      // Validate URL format
      try {
        new URL(url);
      } catch (e) {
        return res.status(400).json({
          error: 'Invalid URL format',
          details: 'URL must be a valid HTTP/HTTPS URL'
        });
      }

      // Validate format if provided
      if (format && !['png', 'jpeg', 'webp'].includes(format)) {
        return res.status(400).json({
          error: 'Invalid format',
          details: 'Format must be png, jpeg, or webp'
        });
      }

      // Validate quality if provided
      if (quality !== undefined && (quality < 1 || quality > 100)) {
        return res.status(400).json({
          error: 'Invalid quality',
          details: 'Quality must be between 1 and 100'
        });
      }

      // Validate delay if provided
      if (delay !== undefined && (delay < 0 || delay > 30000)) {
        return res.status(400).json({
          error: 'Invalid delay',
          details: 'Delay must be between 0 and 30000 milliseconds'
        });
      }

      // Capture screenshot
      const screenshotOptions = {
        fullPage: fullPage !== undefined ? fullPage : true,
        format: format || 'png',
        quality: quality || 90,
        delay: delay || 0
      };

      console.log('Capturing screenshot with options:', screenshotOptions);
      const screenshotBuffer = await screenshotService.captureScreenshot(url, screenshotOptions);

      // Upload to GCS
      console.log('Uploading screenshot to GCS...');
      const uploadResult = await storageService.uploadScreenshot(screenshotBuffer, {
        format: screenshotOptions.format
      });

      // Return success response
      const duration = Date.now() - startTime;

      console.log(`Screenshot request completed successfully in ${duration}ms`);

      res.json({
        success: true,
        screenshotUrl: uploadResult.url,
        metadata: {
          url: url,
          fileName: uploadResult.fileName,
          format: screenshotOptions.format,
          fullPage: screenshotOptions.fullPage,
          capturedAt: new Date().toISOString(),
          fileSize: uploadResult.fileSize,
          contentType: uploadResult.contentType,
          processingTime: duration
        }
      });

    } catch (error) {
      const duration = Date.now() - startTime;

      console.error(`Screenshot capture error after ${duration}ms:`, error.message);
      console.error('Full error:', error);

      // Handle timeout errors specifically with 504 status
      if (error instanceof TimeoutError || error.isTimeout) {
        return res.status(504).json({
          error: 'Screenshot capture timed out',
          details: error.message,
          timeout: true,
          operation: error.operation || 'unknown',
          timeoutMs: error.timeout,
          elapsedMs: duration,
          retryable: true
        });
      }

      // Handle other errors with 500 status
      res.status(500).json({
        error: 'Failed to capture screenshot',
        details: error.message,
        elapsedMs: duration,
        retryable: false
      });
    }
  }
}

module.exports = new ScreenshotController();
