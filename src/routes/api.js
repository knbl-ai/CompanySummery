const express = require('express');
const router = express.Router();
const analyzerController = require('../controllers/analyzerController');
const screenshotController = require('../controllers/screenshotController');
const concurrencyMiddleware = require('../middleware/concurrency');

router.post('/analyze', analyzerController.analyzeUrl.bind(analyzerController));

// Screenshot endpoint with concurrency limiting (max 5 concurrent by default)
router.post('/screenshot', concurrencyMiddleware(), screenshotController.captureScreenshot.bind(screenshotController));

module.exports = router;
