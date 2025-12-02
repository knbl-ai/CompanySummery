# Image Extraction API Usage Guide

Complete guide on how to extract images from web pages using the Company Analyzer image extraction endpoint.

## Table of Contents

- [Quick Start](#quick-start)
- [API Endpoint Details](#api-endpoint-details)
- [Using cURL](#using-curl)
- [Using JavaScript/Node.js](#using-javascriptnodejs)
- [Using Python](#using-python)
- [Response Examples](#response-examples)
- [Image Classification](#image-classification)
- [Error Handling](#error-handling)
- [Best Practices](#best-practices)

## Quick Start

### Local Development

```bash
curl -X POST http://localhost:8080/api/extract-images \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.github.com"}'
```

### Production

Replace with your actual Cloud Run URL:

```bash
curl -X POST https://company-analyzer-xxxxx-uc.a.run.app/api/extract-images \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.github.com"}'
```

## API Endpoint Details

### Endpoint

```
POST /api/extract-images
```

### Request Headers

```
Content-Type: application/json
```

### Request Body Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | ✓ Yes | - | Website URL to extract images from |
| `options` | object | ✗ No | {} | Extraction options (see below) |

### Options Parameters

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `minWidth` | number | 100 | Minimum image width in pixels |
| `minHeight` | number | 100 | Minimum image height in pixels |
| `classifyImages` | boolean | true | Classify images by type |
| `includeBackgrounds` | boolean | false | Include CSS background images |
| `maxImages` | number | 100 | Maximum number of images to return |

### Response

```json
{
  "success": true,
  "url": "https://www.github.com",
  "totalImages": 25,
  "images": [...],
  "metadata": {
    "processingTime": 15000,
    "totalImages": 25,
    "filteredOut": 5,
    "lazyLoadedCount": 20,
    "elapsedMs": 15000
  }
}
```

## Using cURL

### Basic Extraction

```bash
curl -X POST http://localhost:8080/api/extract-images \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.github.com"}'
```

### With Minimum Dimensions

```bash
curl -X POST http://localhost:8080/api/extract-images \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.bbc.com",
    "options": {
      "minWidth": 300,
      "minHeight": 200
    }
  }'
```

### Extract Only Product Images

```bash
curl -X POST http://localhost:8080/api/extract-images \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.example.com",
    "options": {
      "minWidth": 400,
      "minHeight": 300,
      "classifyImages": true,
      "maxImages": 20
    }
  }'
```

### Include Background Images

```bash
curl -X POST http://localhost:8080/api/extract-images \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.example.com",
    "options": {
      "includeBackgrounds": true
    }
  }'
```

### Pretty Print Response

```bash
curl -X POST http://localhost:8080/api/extract-images \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.github.com"}' \
  | jq '.'
```

### Extract Only Image URLs

```bash
curl -X POST http://localhost:8080/api/extract-images \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.github.com"}' \
  | jq '.images[].src'
```

### Get Summary Statistics

```bash
curl -X POST http://localhost:8080/api/extract-images \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.github.com"}' \
  | jq '{totalImages, processingTime: .metadata.processingTime, lazyLoaded: .metadata.lazyLoadedCount}'
```

## Using JavaScript/Node.js

### Using Fetch (Node.js 18+)

```javascript
async function extractImages(url, options = {}) {
  const response = await fetch('http://localhost:8080/api/extract-images', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      url: url,
      options: options
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(`Image extraction failed: ${error.error}`);
  }

  return await response.json();
}

// Usage
extractImages('https://www.github.com', {
  minWidth: 200,
  minHeight: 150,
  classifyImages: true
})
  .then(result => {
    console.log(`Found ${result.totalImages} images`);
    console.log(`Processing time: ${result.metadata.processingTime}ms`);

    // Print product images only
    const productImages = result.images.filter(img => img.classification === 'product');
    console.log(`\nProduct images (${productImages.length}):`);
    productImages.forEach(img => {
      console.log(`  - ${img.alt || 'No alt text'}: ${img.width}x${img.height}`);
      console.log(`    ${img.src}`);
    });
  })
  .catch(error => {
    console.error('Error:', error.message);
  });
```

### Group Images by Classification

```javascript
async function groupImagesByType(url) {
  const result = await extractImages(url, { classifyImages: true });

  const grouped = result.images.reduce((acc, img) => {
    if (!acc[img.classification]) {
      acc[img.classification] = [];
    }
    acc[img.classification].push(img);
    return acc;
  }, {});

  // Print summary
  console.log('Images by type:');
  Object.entries(grouped).forEach(([type, images]) => {
    console.log(`  ${type}: ${images.length}`);
  });

  return grouped;
}

// Usage
groupImagesByType('https://www.bbc.com')
  .then(grouped => {
    console.log('\nHero images:');
    grouped.hero?.forEach(img => console.log(`  - ${img.src}`));
  });
```

### Download Images

```javascript
const fs = require('fs').promises;
const path = require('path');
const https = require('https');

async function downloadImage(url, filepath) {
  return new Promise((resolve, reject) => {
    https.get(url, (response) => {
      if (response.statusCode !== 200) {
        reject(new Error(`Failed to download: ${response.statusCode}`));
        return;
      }

      const file = fs.createWriteStream(filepath);
      response.pipe(file);
      file.on('finish', () => {
        file.close();
        resolve(filepath);
      });
    }).on('error', reject);
  });
}

async function extractAndDownloadImages(url, outputDir, minWidth = 400) {
  // Create output directory
  await fs.mkdir(outputDir, { recursive: true });

  // Extract images
  const result = await extractImages(url, {
    minWidth: minWidth,
    minHeight: 300,
    classifyImages: true
  });

  console.log(`Found ${result.totalImages} images`);

  // Download product images only
  const productImages = result.images.filter(img => img.classification === 'product');
  console.log(`Downloading ${productImages.length} product images...`);

  for (let i = 0; i < productImages.length; i++) {
    const img = productImages[i];
    const ext = path.extname(new URL(img.src).pathname) || '.jpg';
    const filename = `product-${i + 1}${ext}`;
    const filepath = path.join(outputDir, filename);

    try {
      await downloadImage(img.src, filepath);
      console.log(`  ✓ Downloaded: ${filename}`);
    } catch (error) {
      console.error(`  ✗ Failed: ${filename} - ${error.message}`);
    }
  }

  console.log('Download complete!');
}

// Usage
extractAndDownloadImages('https://www.example.com', './images', 500);
```

### Using Axios

```javascript
const axios = require('axios');

async function extractImages(url, options = {}) {
  try {
    const response = await axios.post('http://localhost:8080/api/extract-images', {
      url: url,
      options: options
    });

    return response.data;
  } catch (error) {
    if (error.response) {
      throw new Error(`Image extraction failed: ${error.response.data.error}`);
    } else if (error.request) {
      throw new Error('No response from server');
    } else {
      throw error;
    }
  }
}

// Usage
extractImages('https://www.github.com', { minWidth: 200 })
  .then(result => {
    console.log(`Extracted ${result.totalImages} images`);
  })
  .catch(error => {
    console.error('Error:', error.message);
  });
```

## Using Python

### Basic Usage with Requests

```python
import requests
import json

def extract_images(url, options=None):
    """Extract images from a website."""

    api_url = 'http://localhost:8080/api/extract-images'

    payload = {
        'url': url
    }

    if options:
        payload['options'] = options

    response = requests.post(api_url, json=payload)

    if response.status_code == 200:
        return response.json()
    else:
        error_data = response.json()
        raise Exception(f"Image extraction failed: {error_data.get('error', 'Unknown error')}")

# Usage
try:
    result = extract_images('https://www.github.com', {
        'minWidth': 200,
        'minHeight': 150,
        'classifyImages': True
    })

    print(f"Found {result['totalImages']} images")
    print(f"Processing time: {result['metadata']['processingTime']}ms")

    # Print image classifications
    classifications = {}
    for img in result['images']:
        classification = img['classification']
        classifications[classification] = classifications.get(classification, 0) + 1

    print("\nImages by type:")
    for classification, count in classifications.items():
        print(f"  {classification}: {count}")

except Exception as e:
    print(f"Error: {e}")
```

### Filter and Download Product Images

```python
import requests
from urllib.parse import urlparse
import os

def extract_and_download_products(url, output_dir='./images', min_width=400):
    """Extract product images and download them."""

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Extract images
    result = extract_images(url, {
        'minWidth': min_width,
        'minHeight': 300,
        'classifyImages': True
    })

    print(f"Found {result['totalImages']} total images")

    # Filter product images
    product_images = [
        img for img in result['images']
        if img['classification'] == 'product'
    ]

    print(f"Downloading {len(product_images)} product images...")

    for i, img in enumerate(product_images, 1):
        # Get file extension
        parsed_url = urlparse(img['src'])
        ext = os.path.splitext(parsed_url.path)[1] or '.jpg'

        # Download image
        filename = f"product-{i}{ext}"
        filepath = os.path.join(output_dir, filename)

        try:
            img_response = requests.get(img['src'])
            img_response.raise_for_status()

            with open(filepath, 'wb') as f:
                f.write(img_response.content)

            print(f"  ✓ Downloaded: {filename} ({img['width']}x{img['height']})")
        except Exception as e:
            print(f"  ✗ Failed: {filename} - {e}")

    print("Download complete!")

# Usage
extract_and_download_products('https://www.example.com', './product-images', 500)
```

### Batch Processing

```python
import requests
from concurrent.futures import ThreadPoolExecutor
import time

def extract_images_safe(url, options=None):
    """Extract images with error handling."""
    try:
        start = time.time()
        result = extract_images(url, options)
        elapsed = time.time() - start

        return {
            'url': url,
            'success': True,
            'totalImages': result['totalImages'],
            'processingTime': result['metadata']['processingTime'],
            'elapsed': elapsed
        }
    except Exception as e:
        return {
            'url': url,
            'success': False,
            'error': str(e)
        }

def extract_from_multiple_sites(urls, options=None, max_workers=3):
    """Extract images from multiple websites in parallel."""

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(
            lambda url: extract_images_safe(url, options),
            urls
        ))

    # Print summary
    successful = sum(1 for r in results if r['success'])
    print(f"\nCompleted: {successful}/{len(results)} successful\n")

    for result in results:
        if result['success']:
            print(f"✓ {result['url']}")
            print(f"  Images: {result['totalImages']}, Time: {result['elapsed']:.1f}s")
        else:
            print(f"✗ {result['url']}")
            print(f"  Error: {result['error']}")

    return results

# Usage
websites = [
    'https://www.github.com',
    'https://www.bbc.com',
    'https://www.example.com'
]

results = extract_from_multiple_sites(websites, {
    'minWidth': 200,
    'classifyImages': True
})
```

## Response Examples

### Successful Response

```json
{
  "success": true,
  "url": "https://www.github.com",
  "totalImages": 25,
  "images": [
    {
      "src": "https://github.githubassets.com/assets/hero-blur-bg-06a749e2054a.webp",
      "srcset": null,
      "alt": "GitHub hero background",
      "width": 1029,
      "height": 681,
      "format": "webp",
      "position": {
        "x": -140,
        "y": 310,
        "visible": true
      },
      "classification": "hero",
      "isLazyLoaded": false
    },
    {
      "src": "https://github.githubassets.com/assets/product-mobile.png",
      "srcset": "https://github.githubassets.com/assets/product-mobile@2x.png 2x",
      "alt": "GitHub Mobile app",
      "width": 800,
      "height": 600,
      "format": "png",
      "position": {
        "x": 200,
        "y": 800,
        "visible": true
      },
      "classification": "product",
      "isLazyLoaded": true
    }
  ],
  "metadata": {
    "processingTime": 19516,
    "totalImages": 25,
    "filteredOut": 5,
    "lazyLoadedCount": 24,
    "elapsedMs": 19516
  }
}
```

### Timeout Error (504)

```json
{
  "success": false,
  "error": "Image extraction timed out",
  "details": "Operation exceeded 60000ms timeout",
  "timeout": true,
  "operation": "Image extraction",
  "elapsedMs": 60000,
  "retryable": true
}
```

### Validation Error (400)

```json
{
  "success": false,
  "error": "URL is required",
  "details": "Please provide a valid URL in the request body"
}
```

## Image Classification

### Classification Types

| Type | Description | Typical Dimensions | Position |
|------|-------------|-------------------|----------|
| **hero** | Large featured/banner images | > 800px wide, > 400px tall | Top 20% of page, full-width |
| **product** | Product/merchandise images | 300-800px | Mid-page, with product keywords |
| **logo** | Company/brand logos | < 300px | Header/nav area |
| **icon** | Small UI icons | < 100px | Throughout page |
| **thumbnail** | Preview/gallery images | 100-400px | Grid layouts |
| **content** | Regular article/content images | Varies | Article/content areas |

### Classification Algorithm

Images are classified based on:
- **Size**: Width and height in pixels
- **Position**: Location on the page (x, y coordinates)
- **Context**: Alt text, src path, CSS classes
- **Keywords**: Product-related terms in attributes
- **Parent elements**: Header, nav, article, etc.

## Error Handling

### Common Errors

| Status Code | Error | Cause | Solution |
|-------------|-------|-------|----------|
| 400 | URL is required | Missing URL in request | Include `url` field in request body |
| 400 | Invalid URL format | Malformed URL | Use valid HTTP/HTTPS URL |
| 400 | Invalid minWidth | Non-numeric value | Use positive number |
| 504 | Gateway Timeout | Page took > 60s | Retry or use simpler page |
| 500 | Failed to load page | Page unavailable | Check URL and retry |

### Error Handling Best Practices

```javascript
async function extractImagesWithRetry(url, options = {}, maxRetries = 3) {
  let lastError;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      console.log(`Attempt ${attempt}/${maxRetries} for ${url}`);

      const response = await fetch('http://localhost:8080/api/extract-images', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, options }),
      });

      if (response.status === 504) {
        console.log('Request timed out, retrying...');
        lastError = new Error('Timeout');
        await new Promise(resolve => setTimeout(resolve, attempt * 2000));
        continue;
      }

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error);
      }

      return data;

    } catch (error) {
      lastError = error;
      if (attempt < maxRetries) {
        await new Promise(resolve => setTimeout(resolve, attempt * 2000));
      }
    }
  }

  throw new Error(`Failed after ${maxRetries} attempts: ${lastError.message}`);
}
```

## Best Practices

### 1. Set Appropriate Minimum Dimensions

```javascript
// Filter out icons and tracking pixels
const options = {
  minWidth: 200,
  minHeight: 150
};
```

### 2. Limit Results for Performance

```javascript
// Get only top 20 images
const options = {
  maxImages: 20
};
```

### 3. Use Classification for Filtering

```javascript
// Extract only product images
const result = await extractImages(url, { classifyImages: true });
const productImages = result.images.filter(img => img.classification === 'product');
```

### 4. Handle Large Result Sets

```javascript
// Process images in chunks
const images = result.images;
const chunkSize = 10;

for (let i = 0; i < images.length; i += chunkSize) {
  const chunk = images.slice(i, i + chunkSize);
  await processImageChunk(chunk);
}
```

### 5. Respect Rate Limits

```javascript
// Process sites with delay
for (const url of urls) {
  await extractImages(url);
  await new Promise(resolve => setTimeout(resolve, 2000)); // 2s delay
}
```

### 6. Cache Results

```javascript
const cache = new Map();

async function extractImagesWithCache(url, options = {}, maxAge = 3600000) {
  const cacheKey = `${url}-${JSON.stringify(options)}`;
  const cached = cache.get(cacheKey);

  if (cached && Date.now() - cached.timestamp < maxAge) {
    return cached.result;
  }

  const result = await extractImages(url, options);
  cache.set(cacheKey, { result, timestamp: Date.now() });
  return result;
}
```

## Related Documentation

- [README.md](./README.md) - Main project documentation
- [SCREENSHOT_API_GUIDE.md](./SCREENSHOT_API_GUIDE.md) - Screenshot capture guide
- [DEPLOYMENT.md](./DEPLOYMENT.md) - Deployment guide
- [.env.example](./.env.example) - Configuration template
