# Screenshot API Usage Guide

Complete guide on how to capture screenshots using the Company Analyzer screenshot endpoint.

## Table of Contents

- [Quick Start](#quick-start)
- [API Endpoint Details](#api-endpoint-details)
- [Using cURL](#using-curl)
- [Using JavaScript/Node.js](#using-javascriptnodejs)
- [Using Python](#using-python)
- [Using Postman](#using-postman)
- [Using Browser Fetch API](#using-browser-fetch-api)
- [Advanced Examples](#advanced-examples)
- [Response Examples](#response-examples)
- [Error Handling](#error-handling)

## Quick Start

### Local Development

```bash
curl -X POST http://localhost:8080/api/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

### Production

```bash
# Replace with your actual Cloud Run URL
curl -X POST https://company-analyzer-xxxxx-uc.a.run.app/api/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

## API Endpoint Details

### Endpoint

```
POST /api/screenshot
```

### Request Headers

```
Content-Type: application/json
```

### Request Body Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | ✓ Yes | - | Website URL to capture |
| `fullPage` | boolean | ✗ No | `true` | Capture full scrollable page |
| `publicAccess` | boolean | ✗ No | `true` | Make screenshot publicly accessible |

### Response

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

## Using cURL

### Basic Screenshot (Default Settings)

```bash
curl -X POST http://localhost:8080/api/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.apple.com"}'
```

### Full Page Screenshot (Explicit)

```bash
curl -X POST http://localhost:8080/api/screenshot \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.apple.com",
    "fullPage": true
  }'
```

### Viewport-Only Screenshot

Capture only the visible viewport (not the full page):

```bash
curl -X POST http://localhost:8080/api/screenshot \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.apple.com",
    "fullPage": false
  }'
```

### Private Screenshot (Signed URL)

Generate a signed URL instead of public access:

```bash
curl -X POST http://localhost:8080/api/screenshot \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.apple.com",
    "publicAccess": false
  }'
```

### Save Screenshot Directly

```bash
curl -X POST http://localhost:8080/api/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.apple.com"}' \
  | jq -r '.screenshotUrl' \
  | xargs curl -o screenshot.png
```

### Pretty Print Response

```bash
curl -X POST http://localhost:8080/api/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.apple.com"}' \
  | jq '.'
```

## Using JavaScript/Node.js

### Using Fetch (Node.js 18+)

```javascript
async function captureScreenshot(url, options = {}) {
  const response = await fetch('http://localhost:8080/api/screenshot', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      url: url,
      fullPage: options.fullPage ?? true,
      publicAccess: options.publicAccess ?? true,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(`Screenshot failed: ${error.error}`);
  }

  return await response.json();
}

// Usage
captureScreenshot('https://www.apple.com')
  .then(result => {
    console.log('Screenshot URL:', result.screenshotUrl);
    console.log('File size:', (result.metadata.size / 1024 / 1024).toFixed(2), 'MB');
    console.log('Processing time:', result.metadata.processingTime, 'ms');
  })
  .catch(error => {
    console.error('Error:', error.message);
  });
```

### Using Axios

```javascript
const axios = require('axios');

async function captureScreenshot(url, options = {}) {
  try {
    const response = await axios.post('http://localhost:8080/api/screenshot', {
      url: url,
      fullPage: options.fullPage ?? true,
      publicAccess: options.publicAccess ?? true,
    });

    return response.data;
  } catch (error) {
    if (error.response) {
      // Server responded with error
      throw new Error(`Screenshot failed: ${error.response.data.error}`);
    } else if (error.request) {
      // Request made but no response
      throw new Error('No response from server');
    } else {
      // Other errors
      throw error;
    }
  }
}

// Usage
captureScreenshot('https://www.apple.com')
  .then(result => {
    console.log('Screenshot URL:', result.screenshotUrl);
  })
  .catch(error => {
    console.error('Error:', error.message);
  });
```

### Download Screenshot to File

```javascript
const fs = require('fs');
const https = require('https');

async function captureAndDownload(url, outputPath) {
  // Capture screenshot
  const response = await fetch('http://localhost:8080/api/screenshot', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });

  const result = await response.json();

  // Download screenshot
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(outputPath);
    https.get(result.screenshotUrl, (response) => {
      response.pipe(file);
      file.on('finish', () => {
        file.close();
        console.log(`Screenshot saved to ${outputPath}`);
        resolve(outputPath);
      });
    }).on('error', (err) => {
      fs.unlink(outputPath, () => {}); // Delete partial file
      reject(err);
    });
  });
}

// Usage
captureAndDownload('https://www.apple.com', './apple-screenshot.png')
  .then(() => console.log('Done!'))
  .catch(err => console.error('Error:', err));
```

### Batch Screenshots

```javascript
async function captureMultipleScreenshots(urls) {
  const results = [];

  for (const url of urls) {
    try {
      console.log(`Capturing ${url}...`);
      const result = await captureScreenshot(url);
      results.push({ url, success: true, ...result });
      console.log(`✓ ${url} - ${(result.metadata.size / 1024).toFixed(0)}KB`);
    } catch (error) {
      results.push({ url, success: false, error: error.message });
      console.error(`✗ ${url} - ${error.message}`);
    }
  }

  return results;
}

// Usage
const websites = [
  'https://www.apple.com',
  'https://www.google.com',
  'https://www.github.com',
];

captureMultipleScreenshots(websites)
  .then(results => {
    const successful = results.filter(r => r.success).length;
    console.log(`\nCompleted: ${successful}/${results.length} successful`);
  });
```

## Using Python

### Using Requests Library

```python
import requests
import json

def capture_screenshot(url, full_page=True, public_access=True):
    """Capture a screenshot of a website."""

    api_url = 'http://localhost:8080/api/screenshot'

    payload = {
        'url': url,
        'fullPage': full_page,
        'publicAccess': public_access
    }

    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.post(api_url, json=payload, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        error_data = response.json()
        raise Exception(f"Screenshot failed: {error_data.get('error', 'Unknown error')}")

# Usage
try:
    result = capture_screenshot('https://www.apple.com')
    print(f"Screenshot URL: {result['screenshotUrl']}")
    print(f"File size: {result['metadata']['size'] / 1024 / 1024:.2f} MB")
    print(f"Processing time: {result['metadata']['processingTime']}ms")
except Exception as e:
    print(f"Error: {e}")
```

### Download Screenshot to File

```python
import requests
from pathlib import Path

def capture_and_download(url, output_path):
    """Capture screenshot and download to file."""

    # Capture screenshot
    api_url = 'http://localhost:8080/api/screenshot'
    response = requests.post(api_url, json={'url': url})
    response.raise_for_status()

    result = response.json()
    screenshot_url = result['screenshotUrl']

    # Download screenshot
    img_response = requests.get(screenshot_url)
    img_response.raise_for_status()

    # Save to file
    Path(output_path).write_bytes(img_response.content)
    print(f"Screenshot saved to {output_path}")

    return output_path

# Usage
try:
    capture_and_download('https://www.apple.com', 'apple-screenshot.png')
except Exception as e:
    print(f"Error: {e}")
```

### Batch Processing

```python
import requests
from concurrent.futures import ThreadPoolExecutor
import time

def capture_screenshot_safe(url):
    """Capture screenshot with error handling."""
    try:
        start = time.time()
        response = requests.post(
            'http://localhost:8080/api/screenshot',
            json={'url': url},
            timeout=120  # 2 minute timeout
        )

        if response.status_code == 200:
            result = response.json()
            elapsed = time.time() - start
            return {
                'url': url,
                'success': True,
                'screenshot_url': result['screenshotUrl'],
                'size_mb': result['metadata']['size'] / 1024 / 1024,
                'elapsed': elapsed
            }
        else:
            return {
                'url': url,
                'success': False,
                'error': response.json().get('error', 'Unknown error')
            }
    except Exception as e:
        return {
            'url': url,
            'success': False,
            'error': str(e)
        }

def capture_multiple_screenshots(urls, max_workers=3):
    """Capture multiple screenshots in parallel."""

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(capture_screenshot_safe, urls))

    # Print summary
    successful = sum(1 for r in results if r['success'])
    print(f"\nCompleted: {successful}/{len(results)} successful")

    for result in results:
        if result['success']:
            print(f"✓ {result['url']} - {result['size_mb']:.2f}MB in {result['elapsed']:.1f}s")
        else:
            print(f"✗ {result['url']} - {result['error']}")

    return results

# Usage
websites = [
    'https://www.apple.com',
    'https://www.google.com',
    'https://www.github.com',
]

results = capture_multiple_screenshots(websites)
```

## Using Postman

### 1. Create New Request

1. Click **New** → **HTTP Request**
2. Set method to **POST**
3. Enter URL: `http://localhost:8080/api/screenshot`

### 2. Set Headers

In the **Headers** tab:
```
Content-Type: application/json
```

### 3. Set Body

In the **Body** tab:
1. Select **raw**
2. Choose **JSON** from dropdown
3. Enter:

```json
{
  "url": "https://www.apple.com",
  "fullPage": true,
  "publicAccess": true
}
```

### 4. Send Request

Click **Send**

### 5. View Response

The response will show:
- Status: `200 OK`
- Body with screenshot URL and metadata

### 6. Open Screenshot

Click the `screenshotUrl` value to open the screenshot in your browser.

## Using Browser Fetch API

### Simple Example

```html
<!DOCTYPE html>
<html>
<head>
    <title>Screenshot Capture</title>
</head>
<body>
    <h1>Screenshot Capture</h1>

    <input type="text" id="urlInput" placeholder="Enter website URL" style="width: 400px;">
    <button onclick="captureScreenshot()">Capture Screenshot</button>

    <div id="result" style="margin-top: 20px;"></div>
    <img id="screenshot" style="max-width: 100%; margin-top: 20px; display: none;">

    <script>
        async function captureScreenshot() {
            const url = document.getElementById('urlInput').value;
            const resultDiv = document.getElementById('result');
            const screenshotImg = document.getElementById('screenshot');

            if (!url) {
                alert('Please enter a URL');
                return;
            }

            resultDiv.innerHTML = 'Capturing screenshot...';
            screenshotImg.style.display = 'none';

            try {
                const response = await fetch('http://localhost:8080/api/screenshot', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        url: url,
                        fullPage: true
                    }),
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.error || 'Screenshot failed');
                }

                const result = await response.json();

                // Display result
                resultDiv.innerHTML = `
                    <strong>Success!</strong><br>
                    Size: ${(result.metadata.size / 1024 / 1024).toFixed(2)} MB<br>
                    Processing time: ${result.metadata.processingTime}ms<br>
                    <a href="${result.screenshotUrl}" target="_blank">Open Screenshot</a>
                `;

                // Show screenshot
                screenshotImg.src = result.screenshotUrl;
                screenshotImg.style.display = 'block';

            } catch (error) {
                resultDiv.innerHTML = `<strong>Error:</strong> ${error.message}`;
            }
        }
    </script>
</body>
</html>
```

## Advanced Examples

### With Retry Logic

```javascript
async function captureScreenshotWithRetry(url, maxRetries = 3) {
  let lastError;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      console.log(`Attempt ${attempt}/${maxRetries} for ${url}`);

      const response = await fetch('http://localhost:8080/api/screenshot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });

      if (response.status === 504) {
        // Timeout - retry
        console.log('Request timed out, retrying...');
        lastError = new Error('Request timed out');
        continue;
      }

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error);
      }

      return await response.json();

    } catch (error) {
      lastError = error;
      if (attempt < maxRetries) {
        const delay = attempt * 2000; // Exponential backoff
        console.log(`Waiting ${delay}ms before retry...`);
        await new Promise(resolve => setTimeout(resolve, delay));
      }
    }
  }

  throw new Error(`Failed after ${maxRetries} attempts: ${lastError.message}`);
}

// Usage
captureScreenshotWithRetry('https://www.apple.com')
  .then(result => console.log('Success:', result.screenshotUrl))
  .catch(error => console.error('Failed:', error.message));
```

### With Progress Tracking

```javascript
async function captureWithProgress(url) {
  const startTime = Date.now();

  console.log(`⏳ Starting screenshot capture for ${url}`);

  // Show progress every 5 seconds
  const progressInterval = setInterval(() => {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
    console.log(`⏳ Still processing... ${elapsed}s elapsed`);
  }, 5000);

  try {
    const response = await fetch('http://localhost:8080/api/screenshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });

    clearInterval(progressInterval);

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error);
    }

    const result = await response.json();
    const totalTime = ((Date.now() - startTime) / 1000).toFixed(1);

    console.log(`✓ Screenshot captured in ${totalTime}s`);
    console.log(`  URL: ${result.screenshotUrl}`);
    console.log(`  Size: ${(result.metadata.size / 1024 / 1024).toFixed(2)} MB`);

    return result;

  } catch (error) {
    clearInterval(progressInterval);
    console.error(`✗ Screenshot failed: ${error.message}`);
    throw error;
  }
}

// Usage
captureWithProgress('https://www.apple.com');
```

## Response Examples

### Successful Response

```json
{
  "success": true,
  "screenshotUrl": "https://storage.googleapis.com/knbl-sma/screenshot-a1b2c3d4-e5f6-7890-a1b2-c3d4e5f67890-1704715234567.png",
  "metadata": {
    "filename": "screenshot-a1b2c3d4-e5f6-7890-a1b2-c3d4e5f67890-1704715234567.png",
    "size": 4285192,
    "uploadedAt": "2024-01-08T15:30:34.567Z",
    "processingTime": 18765
  }
}
```

### Timeout Error Response (504)

```json
{
  "error": "Screenshot capture timed out",
  "details": "Operation exceeded 90000ms timeout",
  "timeout": true,
  "operation": "Screenshot capture",
  "elapsedMs": 90000,
  "retryable": true
}
```

### Validation Error Response (400)

```json
{
  "error": "URL is required"
}
```

### Server Error Response (500)

```json
{
  "error": "Failed to capture screenshot",
  "details": "Navigation timeout of 30000 ms exceeded",
  "elapsedMs": 35234
}
```

## Error Handling

### Common Errors and Solutions

| Status Code | Error | Solution |
|-------------|-------|----------|
| 400 | URL is required | Include `url` in request body |
| 400 | Invalid URL format | Use valid URL starting with http:// or https:// |
| 504 | Gateway Timeout | Increase timeout or retry with simpler page |
| 500 | Navigation timeout | Target site may be slow or down, retry later |
| 500 | Browser launch failed | Server may be overloaded, retry later |

### Error Handling Best Practices

```javascript
async function captureScreenshotSafely(url) {
  try {
    const response = await fetch('http://localhost:8080/api/screenshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });

    const data = await response.json();

    if (!response.ok) {
      // Check if retryable
      if (data.timeout && data.retryable) {
        console.log('Request timed out, please retry');
        return { retryable: true, error: data.error };
      }

      // Non-retryable error
      throw new Error(data.error || 'Screenshot failed');
    }

    return { success: true, data };

  } catch (error) {
    // Network or parsing error
    console.error('Request failed:', error.message);
    return { success: false, error: error.message };
  }
}
```

## Performance Tips

### 1. Use Viewport Screenshots for Speed

Full page screenshots take longer. If you only need the visible area:

```bash
curl -X POST http://localhost:8080/api/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "fullPage": false}'
```

### 2. Respect Concurrency Limits

The server limits concurrent screenshots to **5**. If you need to capture many screenshots:

- Process in batches of 5
- Add delays between batches
- Use retry logic for 503 errors (server busy)

### 3. Monitor Processing Times

Track processing times to identify slow sites:

```javascript
const result = await captureScreenshot(url);
if (result.metadata.processingTime > 30000) {
  console.warn(`Slow screenshot: ${url} took ${result.metadata.processingTime}ms`);
}
```

### 4. Cache Results

Don't capture the same URL repeatedly. Implement caching:

```javascript
const screenshotCache = new Map();

async function captureWithCache(url, maxAge = 3600000) {
  const cached = screenshotCache.get(url);
  if (cached && Date.now() - cached.timestamp < maxAge) {
    return cached.result;
  }

  const result = await captureScreenshot(url);
  screenshotCache.set(url, { result, timestamp: Date.now() });
  return result;
}
```

## Support

For issues with the screenshot API:
- Check the [main README](./README.md) troubleshooting section
- Review [DEPLOYMENT.md](./DEPLOYMENT.md) for configuration issues
- Check Cloud Run logs: `gcloud run services logs read company-analyzer`

## Related Documentation

- [README.md](./README.md) - Main project documentation
- [DEPLOYMENT.md](./DEPLOYMENT.md) - Deployment guide
- [.env.example](./.env.example) - Configuration template
