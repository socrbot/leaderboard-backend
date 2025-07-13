# Google Cloud Run Deployment Guide

## Overview
This document describes the deployment configuration for the leaderboard-backend service on Google Cloud Run.

## Service Configuration
- **Project ID**: alumni-golf-tournament
- **Service Name**: leaderboard-backend
- **Region**: us-east1
- **Platform**: Cloud Run (managed)
- **Service URL**: https://leaderboard-backend-628169335141.us-east1.run.app

## Resource Allocation
- **Memory**: 512Mi
- **CPU**: 1000m (1 vCPU)
- **Min Instances**: 0
- **Max Instances**: 40
- **Concurrency**: 80 requests per instance
- **Timeout**: 300 seconds
- **Execution Environment**: gen2

## Security & Access
- **Service Account**: 628169335141-compute@developer.gserviceaccount.com
- **Authentication**: Unauthenticated (public access)
- **Ingress**: All traffic allowed

## Environment Variables
The service uses the following environment variables:
- `RAPIDAPI_KEY`: API key for RapidAPI services
- `SPORTSDATA_IO_API_KEY`: API key for SportsData.io services

## Secrets
- `FIREBASE_SERVICE_ACCOUNT_KEY_PATH`: Mounted from Google Secret Manager (FireBase_Admin secret)

## Deployment
To deploy the service, run:
```bash
chmod +x deploy.sh
./deploy.sh
```

The deployment script will:
1. Enable required Google Cloud APIs
2. Build and push the Docker image using Cloud Build
3. Deploy to Cloud Run with the exact configuration
4. Output the service URL and helpful commands

## Monitoring & Management
- **View logs**: `gcloud run logs tail leaderboard-backend --region=us-east1 --project=alumni-golf-tournament`
- **Update service**: Use the deploy.sh script or gcloud run deploy command
- **Delete service**: `gcloud run services delete leaderboard-backend --region=us-east1 --project=alumni-golf-tournament`

## API Endpoints
- Base URL: https://leaderboard-backend-628169335141.us-east1.run.app
- Health check: `/api/health`
- Tournaments: `/api/tournaments`
- Other endpoints as defined in the Flask application

## Prerequisites

1. **Google Cloud Account**: Make sure you have a Google Cloud account and billing enabled
2. **gcloud CLI**: Install and authenticate the gcloud CLI
3. **Project Setup**: Create or select a Google Cloud project

## Quick Setup

1. **Install gcloud CLI** (if not already installed):
   ```bash
   # Follow instructions at: https://cloud.google.com/sdk/docs/install
   ```

2. **Authenticate with Google Cloud**:
   ```bash
   gcloud auth login
   gcloud auth application-default login
   ```

3. **Set your project** (replace with your actual project ID):
   ```bash
   gcloud config set project YOUR_PROJECT_ID
   ```

## Deployment Options

### Option 1: Automated Deployment Script (Recommended)

1. **Edit the deployment script**:
   ```bash
   # Open deploy.sh and update these variables:
   PROJECT_ID="your-actual-project-id"
   REGION="us-east1"  # or your preferred region
   ```

2. **Run the deployment**:
   ```bash
   ./deploy.sh
   ```

### Option 2: Manual Deployment

1. **Enable required APIs**:
   ```bash
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com containerregistry.googleapis.com
   ```

2. **Create secrets for API keys**:
   ```bash
   # RapidAPI Key
   echo "your_rapidapi_key" | gcloud secrets create rapidapi-key --data-file=-
   
   # SportsData.io Key
   echo "your_sportsdata_key" | gcloud secrets create sportsdata-api-key --data-file=-
   ```

3. **Build and deploy**:
   ```bash
   # Build the image
   gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/leaderboard-backend
   
   # Deploy to Cloud Run
   gcloud run deploy leaderboard-backend \
     --image gcr.io/YOUR_PROJECT_ID/leaderboard-backend \
     --platform managed \
     --region us-east1 \
     --allow-unauthenticated \
     --port 8080 \
     --memory 1Gi \
     --set-env-vars "FLASK_ENV=production" \
     --set-secrets "RAPIDAPI_KEY=rapidapi-key:latest,SPORTSDATA_IO_API_KEY=sportsdata-api-key:latest"
   ```

### Option 3: Cloud Build CI/CD

1. **Set up Cloud Build trigger**:
   ```bash
   gcloud builds triggers create github \
     --repo-name=leaderboard-backend \
     --repo-owner=YOUR_GITHUB_USERNAME \
     --branch-pattern="^main$" \
     --build-config=cloudbuild.yaml
   ```

## Post-Deployment

1. **Get your service URL**:
   ```bash
   gcloud run services describe leaderboard-backend --region=us-east1 --format='value(status.url)'
   ```

2. **Update your frontend** to use the new backend URL:
   ```javascript
   // In your frontend apiConfig.js
   export const BACKEND_BASE_URL = "https://your-service-url.run.app/api";
   ```

3. **Test the deployment**:
   ```bash
   curl https://your-service-url.run.app/api/tournaments
   ```

## Monitoring and Logs

- **View logs**: `gcloud run logs tail leaderboard-backend --region=us-east1`
- **Monitor in Console**: https://console.cloud.google.com/run
- **View metrics**: https://console.cloud.google.com/monitoring

## Troubleshooting

- **Build failures**: Check `gcloud builds log` for detailed error messages
- **Runtime errors**: Check Cloud Run logs in the console
- **Permission issues**: Ensure your service account has the necessary permissions
- **Secrets not found**: Verify secrets are created and accessible

## Cost Optimization

- **CPU allocation**: Start with 1 CPU, scale down if not needed
- **Memory**: 1GB is usually sufficient, monitor usage
- **Min instances**: Keep at 0 to avoid unnecessary costs
- **Max instances**: Adjust based on expected traffic

## Security

- **API Keys**: Always use Secret Manager, never hardcode in code
- **CORS**: Configure properly for your frontend domain
- **Authentication**: Consider adding authentication for production use
