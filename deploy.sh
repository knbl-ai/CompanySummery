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
SCREENSHOT_POST_LOAD_DELAY=$SCREENSHOT_POST_LOAD_DELAY,\
IMAGE_EXTRACTION_TIMEOUT=$IMAGE_EXTRACTION_TIMEOUT,\
IMAGE_MIN_WIDTH=$IMAGE_MIN_WIDTH,\
IMAGE_MIN_HEIGHT=$IMAGE_MIN_HEIGHT,\
IMAGE_INCLUDE_BACKGROUNDS=$IMAGE_INCLUDE_BACKGROUNDS"

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
echo "Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory 4Gi \
  --cpu 2 \
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
