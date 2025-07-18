#!/bin/bash

# Optimized Golf Leaderboard Backend Deployment Script
# This script deploys the backend to Google Cloud Run with optimizations

set -e

# Configuration - Updated with your project details
PROJECT_ID="alumni-golf-tournament"
REGION="us-east1"
SERVICE_NAME="leaderboard-backend"
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"

echo "🏌️ Starting optimized deployment to Google Cloud Run..."
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"
echo ""

# Check if gcloud is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo "❌ Error: Not authenticated with gcloud"
    echo "Please run: gcloud auth login"
    exit 1
fi

# Check if required environment variables are set
if [ -z "$RAPIDAPI_KEY" ]; then
    echo "❌ Error: RAPIDAPI_KEY environment variable not set"
    echo "Please set it with: export RAPIDAPI_KEY=your_key_here"
    exit 1
fi

if [ -z "$SPORTSDATA_IO_API_KEY" ]; then
    echo "❌ Error: SPORTSDATA_IO_API_KEY environment variable not set"
    echo "Please set it with: export SPORTSDATA_IO_API_KEY=your_key_here"
    exit 1
fi

echo "✅ Environment variables verified"

# Enable required APIs
echo "📋 Enabling required Google Cloud APIs..."
gcloud services enable run.googleapis.com \
    cloudbuild.googleapis.com \
    containerregistry.googleapis.com \
    secretmanager.googleapis.com \
    --project=$PROJECT_ID

# Build the container image
echo "🏗️  Building container image..."
gcloud builds submit --tag $IMAGE_NAME --project=$PROJECT_ID

# Deploy to Cloud Run (matching existing service configuration exactly)
echo "🚀 Deploying to Cloud Run..."
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
    --service-account "628169335141-compute@developer.gserviceaccount.com" \
    --set-env-vars "RAPIDAPI_KEY=ed588908c5mshd39b6ec2c9168a5p142e26jsnd2c9925b5e53,SPORTSDATA_IO_API_KEY=3281e31df787425a9da2bc39e7c2889b" \
    --set-secrets "FIREBASE_SERVICE_ACCOUNT_KEY_PATH=FireBase_Admin:latest" \
    --project=$PROJECT_ID

# Get the service URL
SERVICE_URL="https://$SERVICE_NAME-628169335141.$REGION.run.app"

echo ""
echo "✅ Deployment completed successfully!"
echo "🌐 Service URL: $SERVICE_URL"
echo ""
echo "📝 Next steps:"
echo "1. Test the deployment: curl $SERVICE_URL/api/tournaments"
echo "2. Monitor logs: gcloud logs tail --project=$PROJECT_ID"
echo ""
echo "🔧 Useful commands:"
echo "  View logs: gcloud run logs tail $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
echo "  Update service: gcloud run deploy $SERVICE_NAME --image $IMAGE_NAME --region=$REGION --project=$PROJECT_ID"
echo "  Delete service: gcloud run services delete $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
