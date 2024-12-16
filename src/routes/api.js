const express = require('express');
const router = express.Router();
const analyzerController = require('../controllers/analyzerController');

router.post('/analyze', analyzerController.analyzeUrl.bind(analyzerController));

module.exports = router;
