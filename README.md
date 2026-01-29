# ADK Agent Service with Firestore Session Management

A Google Cloud Run deployment of an ADK (Agent Development Kit) agent powered by Gemini 2.5 Flash, with persistent session storage in Google Cloud Firestore.

## Project Overview

This project deploys a conversational AI agent to Google Cloud Run that:
- Uses **Gemini 2.5 Flash** language model for intelligent responses
- Stores user sessions and conversation history in **Google Cloud Firestore**
- Provides both REST API and web-based UI for interaction
- Scales automatically based on traffic demand

## Live Service

**Service URL:** `https://adk-agent-service-975087229168.asia-southeast1.run.app`

- **Web UI:** `/dev-ui`
- **API Documentation:** `/docs`
- **List Available Agents:** `/list-apps`

## Project Structure

```
project-2/
├── main.py                      # FastAPI entry point + Firestore service registration
├── firestore_session_service.py # Custom Firestore session implementation
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Container configuration (Python 3.11)
├── .dockerignore                # Files to exclude from container
└── my_agent/                    # Agent package (valid Python name)
    ├── __init__.py
    └── agent.py                 # Root agent definition
```

**Note:** `main.py` now includes both the FastAPI app setup and the Firestore session service registration (previously in separate `services.py`).

## Deployment Details

### Deployment Command (Cheapest Configuration)

```bash
gcloud run deploy adk-agent-service \
    --source . \
    --region asia-southeast1 \
    --project loop-470211 \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=loop-470211" \
    --set-env-vars "GOOGLE_CLOUD_LOCATION=asia-southeast1" \
    --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=True" \
    --memory 512Mi \
    --cpu 1 \
    --timeout 60 \
    --min-instances 0 \
    --max-instances 5 \
    --cpu-throttling \
    --allow-unauthenticated
```

**Cost Optimization:**
- `--memory 512Mi` - Minimum memory allocation (cheapest)
- `--cpu 1` - Single CPU (cheapest)
- `--cpu-throttling` - CPU only allocated during requests (cheaper)
- `--min-instances 0` - Scales to zero when idle (no idle cost)
- `--max-instances 5` - Limits maximum scale (cost cap)
- `--timeout 60` - Shorter timeout to avoid long-running costs

### Configuration

| Variable | Value | Purpose |
|----------|-------|---------|
| `GOOGLE_CLOUD_PROJECT` | `loop-470211` | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | `asia-southeast1` | Region for Vertex AI |
| `GOOGLE_GENAI_USE_VERTEXAI` | `True` | Use Vertex AI for Gemini access |
| `PORT` | `8080` | Server port (set by Cloud Run) |

### Resources (Cheapest Configuration)

- **Memory:** 512 MiB (minimum)
- **CPU:** 1 vCPU (minimum)
- **CPU Throttling:** Enabled (CPU only active during requests)
- **Timeout:** 60 seconds
- **Min Instances:** 0 (scales down to zero when idle - no idle cost)
- **Max Instances:** 5 (cost cap during high traffic)
- **Region:** Asia Southeast 1 (Singapore)

**Monthly Cost Estimate (Low Traffic):**
- ~$0.00 when idle (scales to zero)
- ~$0.05-$0.50 per month for light usage (few requests per day)
- Only charged for actual request processing time + Firestore operations

## Session Storage

Sessions are persisted in Google Cloud Firestore with the following structure:

```
Firestore Collections:
├── adk_sessions/
│   └── {app_name}/users/{user_id}/sessions/{session_id}
├── adk_app_states/
│   └── {app_name}
└── adk_user_states/
    └── {app_name}/users/{user_id}
```

Each session stores:
- User messages and agent responses
- Conversation history (events)
- Application state
- User-specific state
- Session metadata (timestamps, etc.)

## API Endpoints

### List Available Agents
```bash
GET /list-apps
```

Response:
```json
["my_agent"]
```

### Create or Manage Sessions
Sessions are managed through the ADK FastAPI endpoints. See `/docs` for full API documentation.

### Web UI
Interactive web interface available at `/dev-ui` for testing the agent.

## Architecture

### Components

1. **FastAPI App + Service Registry** (`main.py`)
   - Serves the ADK agent endpoints
   - Handles HTTP requests and responses
   - Enables web UI and API documentation
   - Registers custom `FirestoreSessionService`
   - Maps `firestore://` URI scheme to session service factory

2. **Firestore Session Service** (`firestore_session_service.py`)
   - Implements `BaseSessionService` interface
   - Persists sessions to Google Cloud Firestore
   - Manages state deltas (app, user, session)
   - Handles async operations for performance

3. **Agent** (`my_agent/agent.py`)
   - Defines `root_agent` using Gemini 2.5 Flash
   - Single entry point for user interactions
   - Auto-discovered by ADK's `get_fast_api_app()`

### Key Design Decisions

- **Package naming:** Agent is in `my_agent/` (valid Python name) rather than `project-2/` (contains hyphen)
- **Session service registration:** Uses ADK's URI-based service discovery pattern
- **Async architecture:** All Firestore operations are async for Cloud Run performance
- **Container:** Python 3.11-slim for stability and security
- **Non-root user:** Container runs as unprivileged `appuser` for security

## Local Development

### Prerequisites
- Python 3.11+
- Google Cloud project with Firestore enabled
- GCP credentials (Application Default Credentials)

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
export GOOGLE_GENAI_USE_VERTEXAI=True

# Run locally
python main.py
```

Visit `http://localhost:8080/dev-ui` for the web interface.

## Dependencies

- `google-adk>=1.0.0` - Agent Development Kit framework
- `google-cloud-firestore>=2.0.0` - Firestore database client
- `google-genai` - Google GenAI library
- `uvicorn` - ASGI web server
- `fastapi` - Web framework

## GCP Setup Requirements

### Enable APIs
```bash
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    firestore.googleapis.com \
    aiplatform.googleapis.com \
    --project=loop-470211
```

### Create Firestore Database
```bash
gcloud firestore databases create \
    --location=asia-southeast1 \
    --type=firestore-native \
    --project=loop-470211
```

## Troubleshooting

### Service fails to start
Check Cloud Run logs:
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=adk-agent-service" \
    --project=loop-470211 \
    --limit=50
```

### Agent not detected
Ensure agent package has valid Python name (no hyphens) and `__init__.py` exports `root_agent`.

### Firestore permission denied
Verify service account has `roles/datastore.user` IAM role on the project.

## Security Considerations

- Container runs as non-root user
- Firestore uses project-level IAM for access control
- Environment variables for sensitive config (project ID)
- No hardcoded credentials in code
- Uses Google Cloud's Application Default Credentials

## Cost Optimization

- **Min instances = 0:** Scales to zero when idle (no running cost)
- **Memory = 512 MiB:** Minimum allocation (cheapest option)
- **CPU = 1:** Single CPU with throttling (cheapest option)
- **CPU Throttling:** CPU only allocated during active requests
- **Timeout = 60s:** Short timeout to minimize long-running request costs
- **Max instances = 5:** Cost cap to prevent unexpected high bills
- **Firestore:** Pay-per-read/write model (minimal cost for light traffic)

**Expected Monthly Cost:**
- $0.00 when idle (no usage)
- $0.05-$0.50 for light usage (a few requests per day)
- Only pay for actual compute time + Firestore operations

## Future Enhancements

- Add authentication/authorization
- Implement conversation branching and rollback
- Add conversation export/import
- Implement rate limiting and quota management
- Add monitoring and alerting dashboards
- Support for additional language models

## Support

For issues or questions:
1. Check the Cloud Run logs
2. Review ADK documentation
3. Verify GCP API configuration
4. Check Firestore database status in Cloud Console

---

**Last Updated:** 2026-01-29
**Status:** ✅ Deployed and operational
