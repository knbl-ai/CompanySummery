#!/bin/bash

# Exit on any error
set -e

# Load environment variables
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

PROJECT_ID="socialmediaautomationapp"

echo "🔐 Setting up Google Secret Manager..."

# Set project
gcloud config set project $PROJECT_ID

# Create secrets (or update if they exist)
echo "Creating/updating secrets..."

# GCLOUD_PRIVATE_KEY secret
if gcloud secrets describe gcloud-private-key >/dev/null 2>&1; then
  echo "Secret exists, adding new version..."
  echo "$GCLOUD_PRIVATE_KEY" | gcloud secrets versions add gcloud-private-key --data-file=-
else
  echo "Creating new secret..."
  echo "$GCLOUD_PRIVATE_KEY" | gcloud secrets create gcloud-private-key \
    --data-file=- \
    --replication-policy="automatic"
fi

echo "✅ Secrets created/updated successfully!"

# Grant Cloud Run service account access to secrets
SERVICE_ACCOUNT=$(gcloud iam service-accounts list --filter="email~^.*@.*-compute@developer.gserviceaccount.com$" --format="value(email)" | head -1)

echo "Granting access to service account: $SERVICE_ACCOUNT"

gcloud secrets add-iam-policy-binding gcloud-private-key \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/secretmanager.secretAccessor"

echo "✅ Secret Manager setup complete!"
