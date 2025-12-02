# Deployment Guide - Google Cloud Run

This guide provides comprehensive instructions for deploying the Company Analyzer application to Google Cloud Run with Google Cloud Storage and Secret Manager integration.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Initial Google Cloud Setup](#initial-google-cloud-setup)
- [Google Cloud Storage Setup](#google-cloud-storage-setup)
- [Service Account Setup](#service-account-setup)
- [Secret Manager Setup](#secret-manager-setup)
- [First Deployment](#first-deployment)
- [Subsequent Deployments](#subsequent-deployments)
- [Verification and Testing](#verification-and-testing)
- [Monitoring and Debugging](#monitoring-and-debugging)
- [Rollback](#rollback)
- [Cost Optimization](#cost-optimization)

## Prerequisites

### Required Tools

1. **Google Cloud SDK** (gcloud CLI)
```bash
# macOS
brew install --cask google-cloud-sdk

# Linux
curl https://sdk.cloud.google.com | bash
exec -l $SHELL

# Verify installation
gcloud --version
```

2. **Docker**
```bash
# macOS
brew install --cask docker

# Linux
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io

# Verify installation
docker --version
```

3. **Node.js 18+**
```bash
# Verify installation
node --version
npm --version
```

### Required Accounts

- Google Cloud Platform account with billing enabled
- Anthropic API key for Claude AI

## Initial Google Cloud Setup

### 1. Create Google Cloud Project

```bash
# Set your project ID
PROJECT_ID="your-project-id"

# Create project (if not exists)
gcloud projects create $PROJECT_ID --name="Company Analyzer"

# Set as active project
gcloud config set project $PROJECT_ID

# Verify
gcloud config get-value project
```

### 2. Enable Required APIs

```bash
# Enable all necessary APIs
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable containerregistry.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable storage.googleapis.com
gcloud services enable iam.googleapis.com
```

This may take 2-3 minutes.

### 3. Set Default Region

```bash
# Set region (us-central1 recommended for cost and availability)
gcloud config set run/region us-central1

# Verify
gcloud config get-value run/region
```

## Google Cloud Storage Setup

### 1. Create Storage Bucket

```bash
# Set bucket name (must be globally unique)
BUCKET_NAME="your-unique-bucket-name"

# Create bucket
gsutil mb -p $PROJECT_ID -c STANDARD -l US gs://$BUCKET_NAME

# Enable uniform bucket-level access
gsutil uniformbucketlevelaccess set on gs://$BUCKET_NAME

# Verify
gsutil ls -b gs://$BUCKET_NAME
```

### 2. Configure CORS (Optional)

If you need to access screenshots from web browsers:

```bash
# Create cors.json
cat > cors.json << EOF
[
  {
    "origin": ["*"],
    "method": ["GET"],
    "responseHeader": ["Content-Type"],
    "maxAgeSeconds": 3600
  }
]
EOF

# Apply CORS configuration
gsutil cors set cors.json gs://$BUCKET_NAME

# Clean up
rm cors.json
```

## Service Account Setup

### 1. Create Service Account

```bash
# Create service account
gcloud iam service-accounts create company-analyzer-sa \
  --display-name="Company Analyzer Service Account" \
  --description="Service account for Company Analyzer app"

# Get service account email
SA_EMAIL=$(gcloud iam service-accounts list \
  --filter="displayName:Company Analyzer Service Account" \
  --format="value(email)")

echo "Service Account Email: $SA_EMAIL"
```

### 2. Grant Storage Permissions

```bash
# Grant Storage Admin role to service account
gsutil iam ch serviceAccount:$SA_EMAIL:roles/storage.admin gs://$BUCKET_NAME

# Verify permissions
gsutil iam get gs://$BUCKET_NAME
```

### 3. Generate Service Account Key

```bash
# Create keys directory (temporary)
mkdir -p ~/company-analyzer-keys
cd ~/company-analyzer-keys

# Generate key
gcloud iam service-accounts keys create service-account-key.json \
  --iam-account=$SA_EMAIL

# View key details
cat service-account-key.json | jq -r '.client_email'
cat service-account-key.json | jq -r '.private_key'
```

**Important**: Store this key securely. You'll need:
- `client_email` for `GCLOUD_CLIENT_EMAIL`
- `private_key` for `GCLOUD_PRIVATE_KEY`

### 4. Add to .env File

Add the following to your local `.env` file:

```bash
GCLOUD_PROJECT_ID=your-project-id
GCLOUD_STORAGE_BUCKET_NAME=your-bucket-name
GCLOUD_CLIENT_EMAIL=company-analyzer-sa@your-project-id.iam.gserviceaccount.com
GCLOUD_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nYour\nPrivate\nKey\nHere\n-----END PRIVATE KEY-----\n"
```

**Note**: The private key must include literal `\n` characters in the .env file, but will be converted to actual newlines when uploaded to Secret Manager.

## Secret Manager Setup

### 1. Verify Secret Manager API

```bash
# Verify Secret Manager API is enabled
gcloud services list --enabled | grep secretmanager

# If not enabled
gcloud services enable secretmanager.googleapis.com
```

### 2. Run Setup Script

The `setup-secrets.sh` script will:
- Convert private key newlines from literal `\n` to actual newlines
- Create or update the `gcloud-private-key` secret
- Grant Cloud Run service account access to the secret

```bash
# Ensure .env file is configured
source .env

# Make script executable
chmod +x setup-secrets.sh

# Run setup
./setup-secrets.sh
```

**Expected Output**:
```
🔐 Setting up Google Secret Manager...
Creating/updating secrets...
Secret exists, adding new version...
Created version [1] of the secret [gcloud-private-key].
✅ Secrets created/updated successfully!
Granting access to service account: 265264812851-compute@developer.gserviceaccount.com
Updated IAM policy for secret [gcloud-private-key].
✅ Secret Manager setup complete!
```

### 3. Verify Secret

```bash
# Verify secret exists
gcloud secrets describe gcloud-private-key

# Check secret content (first line only)
gcloud secrets versions access latest --secret=gcloud-private-key | head -1
# Should output: -----BEGIN PRIVATE KEY-----

# Verify newlines (should show ~28 lines for RSA key)
gcloud secrets versions access latest --secret=gcloud-private-key | wc -l
```

### 4. Verify Service Account Access

```bash
# Get default compute service account
COMPUTE_SA=$(gcloud iam service-accounts list \
  --filter="email~^.*-compute@developer.gserviceaccount.com$" \
  --format="value(email)" | head -1)

echo "Compute Service Account: $COMPUTE_SA"

# Verify secret access
gcloud secrets get-iam-policy gcloud-private-key
```

You should see the compute service account with `roles/secretmanager.secretAccessor` role.

## First Deployment

### 1. Update deploy.sh Configuration

Edit `deploy.sh` and verify these settings:

```bash
PROJECT_ID="your-project-id"  # Your GCP project ID
REGION="us-central1"          # Your preferred region
SERVICE_NAME="company-analyzer"
```

### 2. Verify .env File

Ensure your `.env` file contains all required variables:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
PORT=8080

# Google Cloud Storage
GCLOUD_PROJECT_ID=your-project-id
GCLOUD_STORAGE_BUCKET_NAME=your-bucket-name
GCLOUD_CLIENT_EMAIL=company-analyzer-sa@your-project-id.iam.gserviceaccount.com
# Note: GCLOUD_PRIVATE_KEY is stored in Secret Manager

# Storage Options
GCS_PUBLIC_ACCESS=true
GCS_SIGNED_URL_EXPIRY=7d

# Timeout Configuration
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

### 3. Make Scripts Executable

```bash
chmod +x deploy.sh
chmod +x setup-secrets.sh
```

### 4. Run First Deployment

```bash
# This will:
# 1. Build Docker image for linux/amd64
# 2. Tag image for Google Container Registry
# 3. Push image to GCR
# 4. Deploy to Cloud Run with all environment variables and secrets

./deploy.sh
```

**Expected Output**:
```
🚀 Starting deployment process...
Setting project to your-project-id...
🏗️  Building Docker image for linux/amd64...
🏷️  Tagging image for GCR...
⬆️  Pushing image to GCR...
🚀 Deploying to Cloud Run with Secret Manager...
Deploying container to Cloud Run service [company-analyzer]...
✓ Deploying... Done.
  ✓ Creating Revision...
  ✓ Routing traffic...
Done.
✅ Deployment completed!
🌍 Service URL:
https://company-analyzer-xxxxx-uc.a.run.app
```

**First deployment typically takes**: 5-10 minutes

### 5. Verify Deployment

```bash
# Check service status
gcloud run services describe company-analyzer \
  --region us-central1 \
  --format='value(status.conditions[0].status)'

# Should output: True

# Get service URL
SERVICE_URL=$(gcloud run services describe company-analyzer \
  --region us-central1 \
  --format='value(status.url)')

echo "Service URL: $SERVICE_URL"
```

## Subsequent Deployments

For updates after the initial deployment:

```bash
# Simply run the deploy script
./deploy.sh
```

**Subsequent deployments typically take**: 3-5 minutes

### What Gets Updated

- Docker image with latest code changes
- Environment variables from .env file
- Cloud Run configuration (memory, CPU, timeout)

### What Does NOT Get Updated

- Secret Manager secrets (use `./setup-secrets.sh` to update)
- Google Cloud Storage bucket settings
- Service account permissions

## Verification and Testing

### 1. Health Check

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe company-analyzer \
  --region us-central1 \
  --format='value(status.url)')

# Test basic connectivity
curl $SERVICE_URL
```

### 2. Test Analyzer Endpoint

```bash
# Test analyzer endpoint
curl -X POST "$SERVICE_URL/api/analyze" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}' | jq
```

**Expected Response**:
```json
{
  "url": "https://example.com",
  "model": "claude-3-haiku-20240307",
  "summary": "..."
}
```

### 3. Test Screenshot Endpoint

```bash
# Test screenshot endpoint
curl -X POST "$SERVICE_URL/api/screenshot" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.apple.com", "fullPage": true}' | jq
```

**Expected Response**:
```json
{
  "success": true,
  "screenshotUrl": "https://storage.googleapis.com/...",
  "metadata": {
    "filename": "screenshot-...",
    "size": 4285192,
    "uploadedAt": "2024-01-15T10:30:00.000Z",
    "processingTime": 18765
  }
}
```

### 4. Verify Screenshot Upload

```bash
# Open the screenshot URL in browser
# Or download with curl
curl -o test-screenshot.png "https://storage.googleapis.com/..."
```

## Monitoring and Debugging

### View Recent Logs

```bash
# Stream logs in real-time
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=company-analyzer" \
  --format='table(timestamp,severity,textPayload)' \
  --limit 50

# Or use Cloud Run UI
gcloud run services logs read company-analyzer \
  --region us-central1
```

### View Error Logs Only

```bash
# Recent errors
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=company-analyzer AND severity>=ERROR" \
  --limit 50 \
  --format json | jq -r '.[] | "\(.timestamp) [\(.severity)] \(.textPayload // .jsonPayload.message)"'
```

### View Timeout Errors

```bash
# Timeout-specific errors
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=company-analyzer AND textPayload=~\"timeout\"" \
  --limit 20 \
  --format json | jq
```

### Check Service Metrics

```bash
# Get service details including metrics
gcloud run services describe company-analyzer \
  --region us-central1 \
  --format yaml

# Check current revision
gcloud run revisions list \
  --service company-analyzer \
  --region us-central1
```

### Common Issues

#### 1. Private Key Decoder Error

**Error**: `error:1E08010C:DECODER routines::unsupported`

**Cause**: Private key in Secret Manager has literal `\n` instead of actual newlines

**Solution**:
```bash
# Re-run secret setup with proper conversion
source .env
printf "%b" "$GCLOUD_PRIVATE_KEY" > /tmp/private-key.pem
cat /tmp/private-key.pem | gcloud secrets versions add gcloud-private-key --data-file=-
rm /tmp/private-key.pem

# Redeploy
./deploy.sh
```

#### 2. Permission Denied on Secret

**Error**: `Permission denied on secret gcloud-private-key`

**Cause**: Compute service account doesn't have access to secret

**Solution**:
```bash
# Get compute service account
COMPUTE_SA=$(gcloud iam service-accounts list \
  --filter="email~^.*-compute@developer.gserviceaccount.com$" \
  --format="value(email)" | head -1)

# Grant access
gcloud secrets add-iam-policy-binding gcloud-private-key \
  --member="serviceAccount:$COMPUTE_SA" \
  --role="roles/secretmanager.secretAccessor"
```

#### 3. Module Not Found (uuid)

**Error**: `Error [ERR_REQUIRE_ESM]: require() of ES Module uuid`

**Cause**: uuid v13+ is ES Module only

**Solution**: Ensure `package.json` uses uuid v9:
```json
{
  "dependencies": {
    "uuid": "^9.0.1"
  }
}
```

#### 4. Out of Memory

**Error**: Container crashes with exit code 137

**Cause**: Chrome/Puppeteer consuming too much memory

**Solution**: Increase memory in `deploy.sh`:
```bash
--memory 4Gi \
```

## Rollback

### Rollback to Previous Revision

```bash
# List recent revisions
gcloud run revisions list \
  --service company-analyzer \
  --region us-central1

# Rollback to specific revision
PREVIOUS_REVISION="company-analyzer-00042-abc"

gcloud run services update-traffic company-analyzer \
  --to-revisions=$PREVIOUS_REVISION=100 \
  --region us-central1
```

### Verify Rollback

```bash
# Check current traffic allocation
gcloud run services describe company-analyzer \
  --region us-central1 \
  --format='value(status.traffic[0].revisionName)'
```

## Cost Optimization

### Current Configuration Costs

With the current configuration:
- **Memory**: 2Gi
- **CPU**: 2
- **Max Instances**: 10
- **Timeout**: 1000s

**Estimated costs** (approximate):
- Light usage (100 requests/day): ~$5-10/month
- Medium usage (1000 requests/day): ~$30-50/month
- Heavy usage (10000 requests/day): ~$200-300/month

### Optimization Strategies

#### 1. Reduce Memory for Analyzer Endpoint

If you only use the analyzer endpoint (no screenshots):

```bash
# In deploy.sh, change:
--memory 1Gi \
--cpu 1 \
```

#### 2. Add Minimum Instances (Reduce Cold Starts)

For production with consistent traffic:

```bash
# In deploy.sh, add:
--min-instances 1 \
```

**Trade-off**: Costs ~$15-20/month for always-on instance, but eliminates cold starts.

#### 3. Reduce Timeout

If screenshots complete quickly:

```bash
# In deploy.sh, change:
--timeout 300 \
```

#### 4. Aggressive Concurrency

If your app handles concurrency well:

```bash
# In deploy.sh, change:
--concurrency 150 \
```

Higher concurrency = fewer instances = lower cost.

#### 5. Use Cloud Storage Lifecycle Policies

Auto-delete old screenshots:

```bash
# Create lifecycle.json
cat > lifecycle.json << EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 30}
      }
    ]
  }
}
EOF

# Apply to bucket
gsutil lifecycle set lifecycle.json gs://$BUCKET_NAME

# Verify
gsutil lifecycle get gs://$BUCKET_NAME
```

This deletes screenshots older than 30 days.

## Environment-Specific Deployments

### Staging Environment

Create a separate staging service:

```bash
# In deploy.sh, change:
SERVICE_NAME="company-analyzer-staging"

# Deploy
./deploy.sh
```

### Production with Custom Domain

```bash
# Map custom domain (requires domain verification)
gcloud run domain-mappings create \
  --service company-analyzer \
  --domain api.yourcompany.com \
  --region us-central1

# Get DNS records to configure
gcloud run domain-mappings describe \
  --domain api.yourcompany.com \
  --region us-central1
```

## Cleanup

To completely remove the deployment:

```bash
# Delete Cloud Run service
gcloud run services delete company-analyzer \
  --region us-central1

# Delete container images
gcloud container images list --repository gcr.io/$PROJECT_ID
gcloud container images delete gcr.io/$PROJECT_ID/company-analyzer --quiet

# Delete secrets
gcloud secrets delete gcloud-private-key

# Delete storage bucket (careful!)
gsutil rm -r gs://$BUCKET_NAME

# Delete service account
gcloud iam service-accounts delete $SA_EMAIL
```

## Additional Resources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Secret Manager Documentation](https://cloud.google.com/secret-manager/docs)
- [Cloud Storage Documentation](https://cloud.google.com/storage/docs)
- [Puppeteer in Cloud Run](https://cloud.google.com/run/docs/tutorials/web-scraping)

## Support

For deployment issues:
1. Check logs: `gcloud run services logs read company-analyzer`
2. Verify secrets: `gcloud secrets describe gcloud-private-key`
3. Check service status: `gcloud run services describe company-analyzer`
4. Review this guide's troubleshooting section

For application issues, see main [README.md](./README.md) troubleshooting section.
