# Company Analyzer

A Node.js application that analyzes company websites by scraping their content and providing AI-generated summaries using Claude.

## Setup

### Local Development
1. Install dependencies:
```bash
npm install
```

2. Create a `.env` file in the root directory with:
```
ANTHROPIC_API_KEY=your_api_key_here
PORT=8080
```

3. Start the server:
```bash
npm start
```

### Docker Deployment

1. Build the Docker image:
```bash
docker build -t company-analyzer .
```

2. Run the container:
```bash
docker run -p 8080:8080 -e ANTHROPIC_API_KEY=your_api_key_here company-analyzer
```

### Google Cloud Run Deployment

1. Build the image:
```bash
docker build -t gcr.io/your-project/company-analyzer .
```

2. Push to Google Container Registry:
```bash
docker push gcr.io/your-project/company-analyzer
```

3. Deploy to Cloud Run:
- Set container port to 8080
- Add ANTHROPIC_API_KEY as an environment variable
- Allocate at least 1GB memory for Chrome/Puppeteer

## API Usage

### Analyze URL
```
POST /api/analyze
Content-Type: application/json

{
    "url": "https://example.com",
    "model": "claude-3-haiku-20240307",  // optional
    "prompt": "Custom analysis prompt"    // optional
}
```

Response:
```json
{
    "url": "https://example.com",
    "model": "claude-3-haiku-20240307",
    "summary": "AI-generated summary of the webpage content"
}
```

## Error Handling

The API returns appropriate error messages with corresponding HTTP status codes:
- 400: Bad Request (missing URL)
- 500: Internal Server Error (scraping or AI processing failed)
# CompanySummery
# CompanySummery
