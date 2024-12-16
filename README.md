# URL Analyzer

A Node.js application that analyzes URLs by scraping their content and providing AI-generated summaries using Claude.

## Setup

1. Install dependencies:
```bash
npm install
```

2. Create a `.env` file in the root directory with the following content:
```
ANTHROPIC_API_KEY=your_api_key_here
PORT=3000
```

3. Start the server:
```bash
npm start
```

For development with auto-reload:
```bash
npm run dev
```

## API Usage

### Analyze URL
```
POST /api/analyze
Content-Type: application/json

{
    "url": "https://example.com"
}
```

Response:
```json
{
    "url": "https://example.com",
    "summary": "AI-generated summary of the webpage content"
}
```

## Error Handling

The API returns appropriate error messages with corresponding HTTP status codes:
- 400: Bad Request (missing URL)
- 500: Internal Server Error (scraping or AI processing failed)
# CompanySummery
