#!/bin/bash

# Optimized Golf Leaderboard Backend Deployment Script
# This script deploys the backend to Google Cloud Run with optimizations
# Usage: ./deploy.sh [prod|staging]  (defaults to prod)

set -e

# Determine environment
ENV="${1:-prod}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/deploy-config/${ENV}.env"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "âŒ Error: Config file not found: $CONFIG_FILE"
    echo "Usage: ./deploy.sh [prod|staging]"
    exit 1
fi

# Load environment configuration
source "$CONFIG_FILE"
IMAGE_NAME="${IMAGE_REGISTRY:-gcr.io/$PROJECT_ID}/$SERVICE_NAME"

echo "ðŸŒï¸ Starting optimized deployment to Google Cloud Run..."
echo "Environment: $ENV"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"
echo ""

# Check if gcloud is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo "âŒ Error: Not authenticated with gcloud"
    echo "Please run: gcloud auth login"
    exit 1
fi

echo "âœ… Environment verified"

# Enable required APIs
echo "ðŸ“‹ Enabling required Google Cloud APIs..."
gcloud services enable run.googleapis.com \
    cloudbuild.googleapis.com \
    containerregistry.googleapis.com \
    secretmanager.googleapis.com \
    --project=$PROJECT_ID

# Build the container image
echo "ðŸ—ï¸  Building container image..."
gcloud builds submit --tag $IMAGE_NAME --project=$PROJECT_ID

# Deploy to Cloud Run (matching existing service configuration exactly)
echo "ðŸš€ Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_NAME \
    --platform managed \
    --region $REGION \
    --allow-unauthenticated \
    --port 8080 \
    --memory 512Mi \
    --cpu 1000m \
    --min-instances 0 \
    --max-instances 40 \
    --concurrency 80 \
    --timeout 300 \
    --execution-environment gen2 \
    --ingress all \
    --service-account "$SERVICE_ACCOUNT" \
    --clear-env-vars \
    --set-secrets "RAPIDAPI_KEY=$RAPIDAPI_SECRET:latest,SPORTSDATA_IO_API_KEY=$SPORTSDATA_SECRET:latest,FIREBASE_SERVICE_ACCOUNT_KEY_PATH=$FIREBASE_ADMIN_SECRET:latest" \
    --project=$PROJECT_ID

# Get the service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --format='value(status.url)')

echo ""
echo "âœ… Deployment completed successfully!"
echo "ðŸŒ Service URL: $SERVICE_URL"
echo ""
echo "ðŸ“ Next steps:"
echo "1. Test the deployment: curl $SERVICE_URL/api/tournaments"
echo "2. Monitor logs: gcloud logs tail --project=$PROJECT_ID"
echo ""
echo "ðŸ”§ Useful commands:"
echo "  View logs: gcloud run logs tail $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
echo "  Update service: gcloud run deploy $SERVICE_NAME --image $IMAGE_NAME --region=$REGION --project=$PROJECT_ID"
echo "  Delete service: gcloud run services delete $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
