# Company Analyzer

A robust Node.js application that analyzes company websites and captures screenshots using AI-powered analysis with Claude and Puppeteer. Features comprehensive timeout protection, concurrency limiting, and optimized content capture.

## Features

- **AI-Powered Analysis**: Scrapes and analyzes website content using Claude AI
- **Screenshot Capture**: Full-page screenshots with lazy-load support and optimal content capture
- **Multi-Level Timeout Protection**: Prevents indefinite hangs with nested timeouts (90s → 80s → operation-level)
- **Concurrency Limiting**: Prevents resource exhaustion with configurable concurrent request limits
- **Google Cloud Storage Integration**: Automatic upload with public and signed URL options
- **Production-Ready**: Deployed on Google Cloud Run with Secret Manager integration

## Architecture

### Timeout Strategy
```
Express Request Timeout (90s)
  └─> Controller Operation Timeout (80s)
      └─> Service Method Timeouts
          ├─> Browser Launch (15s)
          ├─> Page Navigation (30s)
          ├─> Screenshot Capture (20s)
          └─> GCS Upload (15s)
```

### Screenshot Content Capture
- **Wait Strategy**: `networkidle2` - Waits until only 2 network connections remain
- **Auto-Scroll**: Triggers lazy-loaded images and content
- **Image Loading Wait**: Ensures all images complete loading
- **Post-Load Delay**: 5-second delay for JavaScript execution
- **Concurrency Control**: Maximum 5 concurrent screenshot operations

## Setup

### Prerequisites

- Node.js 18+
- Docker (for deployment)
- Google Cloud Project (for deployment)
- Google Cloud Storage bucket
- Google Cloud service account with Storage Admin role

### Local Development

1. **Install dependencies**:
```bash
npm install
```

2. **Create `.env` file** in the root directory:
```bash
# Required
ANTHROPIC_API_KEY=your_claude_api_key
PORT=8080

# Google Cloud Storage (required for screenshot endpoint)
GCLOUD_PROJECT_ID=your-project-id
GCLOUD_STORAGE_BUCKET_NAME=your-bucket-name
GCLOUD_CLIENT_EMAIL=your-service-account@project.iam.gserviceaccount.com
GCLOUD_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nYour\nMulti\nLine\nPrivate\nKey\n-----END PRIVATE KEY-----\n"

# Storage Options
GCS_PUBLIC_ACCESS=true
GCS_SIGNED_URL_EXPIRY=7d

# Timeout Configuration (all values in milliseconds)
SCREENSHOT_REQUEST_TIMEOUT=90000
SCREENSHOT_OPERATION_TIMEOUT=80000
SCREENSHOT_BROWSER_LAUNCH_TIMEOUT=15000
SCREENSHOT_PAGE_NAVIGATION_TIMEOUT=30000
SCREENSHOT_CAPTURE_TIMEOUT=20000
SCREENSHOT_GCS_UPLOAD_TIMEOUT=15000

# Concurrency and Content Capture
SCREENSHOT_MAX_CONCURRENT=5
SCREENSHOT_WAIT_STRATEGY=networkidle2
SCREENSHOT_POST_LOAD_DELAY=5000
```

3. **Start development server**:
```bash
npm run dev
```

The server will start on `http://localhost:8080`.

## API Documentation

### 1. Analyze Website

Scrapes website content and generates AI-powered analysis.

**Endpoint**: `POST /api/analyze`

**Request**:
```json
{
    "url": "https://example.com",
    "model": "claude-3-haiku-20240307",
    "prompt": "Analyze this company's products and services"
}
```

**Parameters**:
- `url` (required): Website URL to analyze
- `model` (optional): Claude model to use (default: claude-3-haiku-20240307)
- `prompt` (optional): Custom analysis prompt

**Response**:
```json
{
    "url": "https://example.com",
    "model": "claude-3-haiku-20240307",
    "summary": "AI-generated analysis of the webpage content..."
}
```

**Status Codes**:
- `200`: Success
- `400`: Bad Request (missing URL)
- `500`: Internal Server Error

### 2. Capture Screenshot

Captures full-page screenshot with optimized content loading.

**Endpoint**: `POST /api/screenshot`

**Request**:
```json
{
    "url": "https://example.com",
    "fullPage": true,
    "publicAccess": true
}
```

**Parameters**:
- `url` (required): Website URL to capture
- `fullPage` (optional): Capture full scrollable page (default: true)
- `publicAccess` (optional): Make screenshot publicly accessible (default: true)

**Response**:
```json
{
    "success": true,
    "screenshotUrl": "https://storage.googleapis.com/your-bucket/screenshot-uuid-timestamp.png",
    "metadata": {
        "filename": "screenshot-uuid-timestamp.png",
        "size": 5428192,
        "uploadedAt": "2024-01-15T10:30:00.000Z",
        "processingTime": 18765
    }
}
```

**Timeout Error Response** (504):
```json
{
    "error": "Screenshot capture timed out",
    "details": "Operation exceeded timeout",
    "timeout": true,
    "operation": "Screenshot capture",
    "elapsedMs": 90000,
    "retryable": true
}
```

**Status Codes**:
- `200`: Success
- `400`: Bad Request (missing/invalid URL)
- `504`: Gateway Timeout (operation exceeded timeout limit)
- `500`: Internal Server Error

## Configuration Guide

### Timeout Settings

Adjust timeouts based on your target websites:

| Setting | Default | Description |
|---------|---------|-------------|
| `SCREENSHOT_REQUEST_TIMEOUT` | 90000ms | Maximum total request time |
| `SCREENSHOT_OPERATION_TIMEOUT` | 80000ms | Maximum screenshot operation time |
| `SCREENSHOT_BROWSER_LAUNCH_TIMEOUT` | 15000ms | Browser initialization timeout |
| `SCREENSHOT_PAGE_NAVIGATION_TIMEOUT` | 30000ms | Page load timeout |
| `SCREENSHOT_CAPTURE_TIMEOUT` | 20000ms | Screenshot capture timeout |
| `SCREENSHOT_GCS_UPLOAD_TIMEOUT` | 15000ms | Cloud Storage upload timeout |

### Content Capture Settings

Optimize for different website types:

| Setting | Default | Options | Description |
|---------|---------|---------|-------------|
| `SCREENSHOT_WAIT_STRATEGY` | networkidle2 | domcontentloaded, load, networkidle0, networkidle2 | When to consider page loaded |
| `SCREENSHOT_POST_LOAD_DELAY` | 5000ms | 0-10000ms | Delay after load for JS execution |
| `SCREENSHOT_MAX_CONCURRENT` | 5 | 1-10 | Maximum concurrent screenshots |

**Wait Strategy Guide**:
- `domcontentloaded`: Fastest, may miss images (use for simple pages)
- `load`: Waits for all resources except async scripts
- `networkidle2`: **Recommended** - Waits until ≤2 network connections remain
- `networkidle0`: Slowest, never completes on pages with persistent connections

### Storage Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `GCS_PUBLIC_ACCESS` | true | Make screenshots publicly accessible |
| `GCS_SIGNED_URL_EXPIRY` | 7d | Signed URL expiration (if not public) |

## Deployment

See [DEPLOYMENT.md](./DEPLOYMENT.md) for comprehensive deployment instructions to Google Cloud Run.

### Quick Deploy

```bash
# Setup secrets (first time only)
./setup-secrets.sh

# Deploy to Cloud Run
./deploy.sh
```

## Performance Benchmarks

Real-world performance with default settings:

| Website | File Size | Processing Time | Status |
|---------|-----------|-----------------|--------|
| apple.com | 4.08 MB | 18.8s | ✓ Success |
| roladin.co.il | 6.75 MB | 18.9s | ✓ Success |
| knbl360.com | 5.42 MB | 25.0s | ✓ Success |
| rafael.co.il | 3.21 MB | 16.2s | ✓ Success |

All requests complete well within the 90-second timeout limit.

## Troubleshooting

### Screenshots Are Incomplete

**Symptoms**: Missing images, blank areas

**Solutions**:
1. Increase `SCREENSHOT_POST_LOAD_DELAY` to 8000-10000ms
2. Keep `SCREENSHOT_WAIT_STRATEGY=networkidle2`
3. Increase `SCREENSHOT_PAGE_NAVIGATION_TIMEOUT` to 45000ms

### Requests Timing Out

**Symptoms**: 504 Gateway Timeout errors

**Solutions**:
1. Increase `SCREENSHOT_REQUEST_TIMEOUT` to 120000ms
2. Increase `SCREENSHOT_OPERATION_TIMEOUT` to 110000ms
3. Check target website response time
4. Reduce `SCREENSHOT_POST_LOAD_DELAY` to 3000ms

### Memory Issues (Cloud Run)

**Symptoms**: Out of memory errors, crashes

**Solutions**:
1. Increase Cloud Run memory allocation (2Gi → 4Gi)
2. Reduce `SCREENSHOT_MAX_CONCURRENT` to 3
3. Add `--max-instances` limit in deploy.sh

### Zombie Chrome Processes

**Symptoms**: Increasing memory usage over time

**Solutions**:
- Already handled by `forceBrowserClose()` with SIGKILL
- Verify no manual browser.launch() calls without proper cleanup
- Check Cloud Run logs for browser close errors

### Private Key Errors in Deployment

**Symptoms**: `error:1E08010C:DECODER routines::unsupported`

**Solution**: Private key must be stored in Google Secret Manager with proper newlines:
```bash
source .env
printf "%b" "$GCLOUD_PRIVATE_KEY" > /tmp/private-key.pem
cat /tmp/private-key.pem | gcloud secrets versions add gcloud-private-key --data-file=-
rm /tmp/private-key.pem
```

## Project Structure

```
CompanyAnalyzer/
├── src/
│   ├── app.js                      # Express application setup
│   ├── controllers/
│   │   ├── analyzerController.js   # Analyzer endpoint handler
│   │   └── screenshotController.js # Screenshot endpoint handler
│   ├── services/
│   │   ├── scrapeService.js        # Web scraping service
│   │   ├── screenshotService.js    # Puppeteer screenshot service
│   │   └── storageService.js       # Google Cloud Storage service
│   ├── routes/
│   │   └── api.js                  # API route definitions
│   ├── middleware/
│   │   ├── timeout.js              # Request timeout middleware
│   │   └── concurrency.js          # Concurrency limiting middleware
│   └── utils/
│       └── timeout.js              # Timeout utilities and wrappers
├── deploy.sh                       # Cloud Run deployment script
├── setup-secrets.sh                # Secret Manager setup script
├── Dockerfile                      # Docker container definition
├── package.json                    # Dependencies
├── .env                           # Environment variables (not in git)
└── .gitignore                     # Git exclusions
```

## Security

### Sensitive Information

The following files contain sensitive information and are excluded from git:
- `.env` - All environment variables including API keys
- `service.yaml` - Deployment configuration with env vars
- `credentials.json` - GCP service account credentials
- `*.pem` - Private key files

### Secret Management

In production, sensitive credentials are stored in Google Secret Manager:
- `GCLOUD_PRIVATE_KEY` - GCS service account private key

All other configuration is passed via environment variables in Cloud Run.

## Testing

### Local Testing

```bash
# Test analyzer endpoint
curl -X POST http://localhost:8080/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Test screenshot endpoint
curl -X POST http://localhost:8080/api/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "fullPage": true}'
```

### Production Testing

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe company-analyzer \
  --region us-central1 \
  --format='value(status.url)')

# Test screenshot endpoint
curl -X POST "$SERVICE_URL/api/screenshot" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.apple.com"}'
```

### Load Testing

```bash
# Install Apache Bench
brew install httpd  # macOS
apt-get install apache2-utils  # Linux

# Create test payload
echo '{"url": "https://example.com"}' > screenshot.json

# Run load test (20 requests, 10 concurrent)
ab -n 20 -c 10 -p screenshot.json -T application/json \
  http://localhost:8080/api/screenshot
```

## Monitoring

### Check Cloud Run Logs

```bash
# Recent errors
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=company-analyzer AND severity>=ERROR" \
  --limit 50 \
  --format json \
  --project socialmediaautomationapp

# Timeout errors
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=company-analyzer AND textPayload=~\"timeout\"" \
  --limit 20 \
  --format json
```

### Monitor Chrome Processes (Local)

```bash
# Check for zombie Chrome processes
ps aux | grep chrome

# Monitor memory usage
watch -n 1 'ps aux | grep node'
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly (local and production)
5. Submit a pull request

## License

MIT

## Support

For issues and questions, please open an issue in the repository.
