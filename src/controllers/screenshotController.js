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
          error: 'URL is required'
        });
      }

      // Validate URL format
      try {
        new URL(url);
      } catch (e) {
        return res.status(400).json({
          error: 'Invalid URL format'
        });
      }

      // Validate format if provided
      if (format && !['png', 'jpeg', 'webp'].includes(format)) {
        return res.status(400).json({
          error: 'Invalid format. Must be png, jpeg, or webp'
        });
      }

      // Validate quality if provided
      if (quality !== undefined && (quality < 1 || quality > 100)) {
        return res.status(400).json({
          error: 'Invalid quality. Must be between 1 and 100'
        });
      }

      // Validate delay if provided
      if (delay !== undefined && (delay < 0 || delay > 30000)) {
        return res.status(400).json({
          error: 'Invalid delay. Must be between 0 and 30000 milliseconds'
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
      console.error('Error name:', error.name);
      console.error('Error isTimeout:', error.isTimeout);
      console.error('Stack trace:', error.stack);

      // Handle timeout errors specifically with 504 status
      if (error instanceof TimeoutError || error.isTimeout) {
        return res.status(504).json({
          error: 'Screenshot capture timed out',
          timeout: true,
          retryable: true
        });
      }

      // Return generic error to client (no internal details)
      res.status(500).json({
        error: 'Failed to capture screenshot',
        retryable: false
      });
    }
  }
}

module.exports = new ScreenshotController();
