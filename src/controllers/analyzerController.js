const scrapeService = require('../services/scrapeService');
const aiService = require('../services/aiService');

class AnalyzerController {
  async analyzeUrl(req, res) {
    try {
      console.log('Received request body:', JSON.stringify(req.body, null, 2));

      const { url, model, prompt } = req.body;

      if (!url) {
        return res.status(400).json({ error: 'URL is required' });
      }

      // Scrape the URL
      const scrapedContent = await scrapeService.scrapeUrl(url);

      console.log("scrapedContent", scrapedContent);

      // Get AI summary using optional model and prompt
      const summary = await aiService.summarizeContent(scrapedContent, model, prompt);

      res.json({
        url: url,
        model: model || "claude-3-haiku-20240307", // Show which model was used
        summary: summary
      });
    } catch (error) {
      console.error('Analysis error:', error.message);
      console.error('Full error:', error);
      res.status(500).json({ error: 'Failed to analyze URL', details: error.message });
    }
  }
}

module.exports = new AnalyzerController();
