const express = require('express');
const router = express.Router();
const analyzerController = require('../controllers/analyzerController');
const screenshotController = require('../controllers/screenshotController');
const imageExtractionController = require('../controllers/imageExtractionController');
const concurrencyMiddleware = require('../middleware/concurrency');
const { urlValidatorMiddleware } = require('../middleware/urlValidator');

// All endpoints use URL validation to prevent SSRF attacks
router.post('/analyze', urlValidatorMiddleware, analyzerController.analyzeUrl.bind(analyzerController));

// Screenshot endpoint with concurrency limiting (max 5 concurrent by default)
router.post('/screenshot', urlValidatorMiddleware, concurrencyMiddleware(), screenshotController.captureScreenshot.bind(screenshotController));

// Image extraction endpoint with concurrency limiting
router.post('/extract-images', urlValidatorMiddleware, concurrencyMiddleware(), imageExtractionController.extractImages.bind(imageExtractionController));

module.exports = router;
