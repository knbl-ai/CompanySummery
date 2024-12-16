const { Anthropic } = require('@anthropic-ai/sdk');

class AiService {
  constructor() {
    if (!process.env.ANTHROPIC_API_KEY) {
      throw new Error('ANTHROPIC_API_KEY is required');
    }
    this.anthropic = new Anthropic({
      apiKey: process.env.ANTHROPIC_API_KEY,
    });
  }

  async summarizeContent(content, model = "claude-3-haiku-20240307", 
    prompt = `Using the provided information from the company's website, write a clear and concise summary of the company. "
    "Focus on:\n"
    "1. What the company does.\n"
    "2. Its key functions and offerings.\n"
    "3. Its unique value proposition for clients or customers.\n\n"
    "4. Ommit premble, go straign to the point.\n"
    "5. Provide conscise answers, avoiding repetititions and generalizations, use as little information as possible.\n\n"
    "Do not include unnecessary preamble or fluff, and ensure the summary is professional and to the point.`) {


      console.log(content);
    try {
      const message = await this.anthropic.messages.create({
        model: model,
        max_tokens: 1024,
        system: "You are a helpful assistant that provides concise summaries of web pages.",
        messages: [{
          role: "user",
          content: `${prompt}.\nTitle: ${content.title}\n\Scraped_data: ${content.content}`
        }]
      });

      return message.content[0].text;
    } catch (error) {
      console.error('AI processing error:', error);
      throw error;
    }
  }
}

module.exports = new AiService();
