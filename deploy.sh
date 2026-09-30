#!/bin/bash

# Exit on any error
set -e

# Load environment variables from .env file
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Set the project ID and other configurations
PROJECT_ID="socialmediaautomationapp"
REGION="us-central1"
SERVICE_NAME="company-analyzer"
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"

# Prepare environment variables string
ENV_VARS="GCLOUD_PROJECT_ID=$GCLOUD_PROJECT_ID,\
GCLOUD_STORAGE_BUCKET_NAME=$GCLOUD_STORAGE_BUCKET_NAME,\
GCLOUD_CLIENT_EMAIL=$GCLOUD_CLIENT_EMAIL,\
GCS_PUBLIC_ACCESS=$GCS_PUBLIC_ACCESS,\
GCS_SIGNED_URL_EXPIRY=$GCS_SIGNED_URL_EXPIRY,\
SCREENSHOT_REQUEST_TIMEOUT=$SCREENSHOT_REQUEST_TIMEOUT,\
SCREENSHOT_OPERATION_TIMEOUT=$SCREENSHOT_OPERATION_TIMEOUT,\
SCREENSHOT_PAGE_NAVIGATION_TIMEOUT=$SCREENSHOT_PAGE_NAVIGATION_TIMEOUT,\
SCREENSHOT_CAPTURE_TIMEOUT=$SCREENSHOT_CAPTURE_TIMEOUT,\
SCREENSHOT_GCS_UPLOAD_TIMEOUT=$SCREENSHOT_GCS_UPLOAD_TIMEOUT,\
SCREENSHOT_MAX_CONCURRENT=$SCREENSHOT_MAX_CONCURRENT,\
SCREENSHOT_POST_LOAD_DELAY=${SCREENSHOT_POST_LOAD_DELAY:-1500},\
SCREENSHOT_LOAD_STATE_TIMEOUT=${SCREENSHOT_LOAD_STATE_TIMEOUT:-10000},\
SCREENSHOT_FONTS_READY_TIMEOUT=${SCREENSHOT_FONTS_READY_TIMEOUT:-3000},\
SCREENSHOT_MAX_FULL_PAGE_VIEWPORTS=${SCREENSHOT_MAX_FULL_PAGE_VIEWPORTS:-3},\
SCREENSHOT_SCROLL_MAX_PX=${SCREENSHOT_SCROLL_MAX_PX:-6000},\
IMAGE_EXTRACTION_TIMEOUT=$IMAGE_EXTRACTION_TIMEOUT,\
IMAGE_MIN_WIDTH=$IMAGE_MIN_WIDTH,\
IMAGE_MIN_HEIGHT=$IMAGE_MIN_HEIGHT,\
IMAGE_INCLUDE_BACKGROUNDS=$IMAGE_INCLUDE_BACKGROUNDS,\
CRAWL_MAX_PAGES=${CRAWL_MAX_PAGES:-8},\
CRAWL_TIME_BUDGET_MS=${CRAWL_TIME_BUDGET_MS:-240000},\
CRAWL_PAGE_TIMEOUT_MS=${CRAWL_PAGE_TIMEOUT_MS:-60000},\
CRAWL_MIN_REMAINING_MS=${CRAWL_MIN_REMAINING_MS:-20000},\
EXTRACTION_POST_LOAD_DELAY=${EXTRACTION_POST_LOAD_DELAY:-1000},\
MAX_CONCURRENT_PAGES=${MAX_CONCURRENT_PAGES:-8},\
CRAWL_PAGE_CONCURRENCY=${CRAWL_PAGE_CONCURRENCY:-6}"

# The four above are set explicitly rather than left to their code defaults so every
# behaviour change can be undone on a running revision, without building anything:
#
#   gcloud run services update company-analyzer --region us-central1 \
#     --update-env-vars CRAWL_PAGE_CONCURRENCY=1,EXTRACTION_POST_LOAD_DELAY=5000
#
# That is sequential page visits and the old settle time — the state this service was in
# before 2026-08-12 — reachable in one command if the concurrent crawl misbehaves.
# Narrower step back, if six pages at once is the part that hurts:
#
#   gcloud run services update company-analyzer --region us-central1 \
#     --update-env-vars CRAWL_PAGE_CONCURRENCY=3,MAX_CONCURRENT_PAGES=6
#
# `CRAWL_PAGE_TIMEOUT_MS=45000` reverts the start-page budget on its own. It costs a crawl
# nothing when the page loads; it only decides how long a slow one is given to prove it.
#
# The capture bounds land the same way. knbl360.com measured 126.1s server-side on
# 2026-08-27 — 30.0s waiting for a `load` that never fires, 21.1s scrolling 15000px it
# never photographed, 5.0s of blind sleep, and 29.3s capturing all 11441px of it. To put
# the whole of that back on a running revision:
#
#   gcloud run services update company-analyzer --region us-central1 \
#     --update-env-vars SCREENSHOT_LOAD_STATE_TIMEOUT=30000,SCREENSHOT_SCROLL_MAX_PX=15000,\
#SCREENSHOT_MAX_FULL_PAGE_VIEWPORTS=100000,SCREENSHOT_POST_LOAD_DELAY=5000
#
# `SCREENSHOT_MAX_FULL_PAGE_VIEWPORTS` is the one to reach for first if a capture comes
# back showing too little of a site: it is the only one of the four that changes what the
# image CONTAINS rather than how long it is worth waiting for.

echo "Starting deployment process..."

# Set the correct project
echo "Setting project to $PROJECT_ID..."
gcloud config set project $PROJECT_ID

# Build the Docker image for linux/amd64 platform
echo "Building Docker image for linux/amd64..."
docker build --platform linux/amd64 -t $SERVICE_NAME .

# Tag the image for Google Container Registry
echo "Tagging image for GCR..."
docker tag $SERVICE_NAME $IMAGE_NAME

# Push the image to Google Container Registry
echo "Pushing image to GCR..."
docker push $IMAGE_NAME

# Deploy to Cloud Run
#
# 4 vCPU / 8Gi, up from 2 / 4Gi. A crawl used to render one page at a time, so the
# instance never held more than one page per context — the context limit bounded memory by
# accident. It now renders up to `MAX_CONCURRENT_PAGES` (8), and rendering is the part of
# a page visit that actually wants CPU.
#
# Roughly cost-neutral rather than an increase: the crawl measured 229s before and 68.9s
# after, so the doubled rate is spent over a third the time. Memory is the cheaper half
# of the bill and OOM is the failure mode that kills the container rather than slowing it,
# so it gets the headroom.
echo "Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory 8Gi \
  --cpu 4 \
  --timeout 300 \
  --port 8080 \
  --max-instances 10 \
  --concurrency 10 \
  --set-env-vars="$ENV_VARS" \
  --set-secrets="GCLOUD_PRIVATE_KEY=gcloud-private-key:latest"

echo "Deployment completed!"

# Get the service URL
echo "Service URL:"
gcloud run services describe $SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --format='value(status.url)'
