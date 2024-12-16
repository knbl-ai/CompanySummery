#!/bin/bash

# Exit on any error
set -e

# Load environment variables from .env file
if [ -f .env ]; then
  export $(cat .env | sed 's/#.*//g' | xargs)
fi

# Set the project ID and other configurations
PROJECT_ID="socialmediaautomationapp"
REGION="us-central1"
SERVICE_NAME="company-analyzer"
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"

# Prepare environment variables string
ENV_VARS="NODE_ENV=production,\
PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium,\
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY"

echo "🚀 Starting deployment process..."

# Set the correct project
echo "Setting project to $PROJECT_ID..."
gcloud config set project $PROJECT_ID

# Build the Docker image for linux/amd64 platform
echo "🏗️  Building Docker image for linux/amd64..."
docker build --platform linux/amd64 -t $SERVICE_NAME .

# Tag the image for Google Container Registry
echo "🏷️  Tagging image for GCR..."
docker tag $SERVICE_NAME $IMAGE_NAME

# Push the image to Google Container Registry
echo "⬆️  Pushing image to GCR..."
docker push $IMAGE_NAME

# Deploy to Cloud Run
echo "🚀 Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 1000 \
  --port 8080 \
  --set-env-vars="$ENV_VARS"

echo "✅ Deployment completed!"

# Get the service URL
echo "🌍 Service URL:"
gcloud run services describe $SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --format='value(status.url)'
