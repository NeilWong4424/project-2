"""FastAPI entry point for Cloud Run deployment."""
import os

# Register custom Firestore session service
from google.adk.cli.service_registry import get_service_registry
from firestore_session_service import FirestoreSessionService


def firestore_session_factory(uri: str, **kwargs) -> FirestoreSessionService:
    """Factory for creating FirestoreSessionService from URI.

    URI format: firestore://[project_id]/[database]
    Example: firestore:///  (uses env vars for project, default database)
    """
    return FirestoreSessionService(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        database="(default)",
        collection_prefix="adk",
    )


# Register the custom Firestore session service
get_service_registry().register_session_service("firestore", firestore_session_factory)

from google.adk.cli.fast_api import get_fast_api_app

# Get the directory where main.py is located (project root)
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Get the FastAPI app from ADK with Firestore session service
app = get_fast_api_app(
    agents_dir=AGENT_DIR,
    session_service_uri="firestore:///",  # Uses custom FirestoreSessionService
    web=True,  # Enable ADK dev UI
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
