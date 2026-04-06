"""
scripts/setup_render.py — Provision Golteris infrastructure on Render via API.

This script creates:
1. A managed Postgres database (golteris-db)
2. A web service (golteris-web) — FastAPI serving API + React frontend
3. A background worker (golteris-worker) — job queue processor

Prerequisites:
- RENDER_API_KEY in .env (get from Render dashboard → Account Settings → API Keys)
- ANTHROPIC_API_KEY in .env (set on the Render services as a secret)
- The GitHub repo (cg0296/golteris-ai-platform) must be accessible to Render

Usage:
    python scripts/setup_render.py

The script is idempotent — it checks for existing resources before creating them.
After running, it prints the live URL and DATABASE_URL for your .env file.

See REQUIREMENTS.md §2.4 (Infrastructure & deploy) and issue #19.
"""

import json
import os
import sys
import time

# Load .env file from project root
# (we do this manually to avoid adding python-dotenv as a script dependency)
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

# ---------------------------------------------------------------------------
# Configuration — change these if you want different names or settings
# ---------------------------------------------------------------------------

RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OWNER_ID = os.environ.get("RENDER_OWNER_ID", "tea-d2gb5nadbo4c73avdrc0")

# Service names — must be unique across your Render account
DB_NAME = "golteris-db"
WEB_NAME = "golteris-web"
WORKER_NAME = "golteris-worker"

# GitHub repo to deploy from
REPO_URL = "https://github.com/cg0296/golteris-ai-platform"
BRANCH = "master"

# Render region and plan
REGION = "oregon"
PLAN = "free"

# Render API base URL
API_BASE = "https://api.render.com/v1"

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

# Using urllib instead of requests to avoid external dependencies.
# This script should run with just the Python standard library.
import urllib.request
import urllib.error


def api_request(method, path, body=None):
    """
    Make an authenticated request to the Render API.

    Args:
        method: HTTP method (GET, POST, DELETE)
        path: API path (e.g., "/postgres")
        body: Optional dict to send as JSON request body

    Returns:
        Parsed JSON response, or None for 204/empty responses

    Raises:
        SystemExit on 4xx/5xx errors with the error message
    """
    url = f"{API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            resp_body = resp.read().decode()
            if resp_body:
                return json.loads(resp_body)
            return None
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"  ERROR {e.code}: {error_body}")
        if e.code >= 400:
            sys.exit(1)


def wait_for_status(resource_type, resource_id, target_status="available", timeout=300):
    """
    Poll a resource until it reaches the target status.

    Args:
        resource_type: "postgres" or "services"
        resource_id: The Render resource ID
        target_status: Status string to wait for (default: "available")
        timeout: Max seconds to wait (default: 300)

    Returns:
        The resource data once it reaches the target status
    """
    print(f"  Waiting for {resource_type}/{resource_id} to become {target_status}...")
    start = time.time()
    while time.time() - start < timeout:
        data = api_request("GET", f"/{resource_type}/{resource_id}")
        # Postgres and services have different response shapes
        resource = data.get("postgres") or data.get("service") or data
        status = resource.get("status", "unknown")
        print(f"    Status: {status}")
        if status == target_status:
            return resource
        time.sleep(10)
    print(f"  TIMEOUT waiting for {target_status} after {timeout}s")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Main setup flow
# ---------------------------------------------------------------------------

def find_existing(resource_type, name):
    """Check if a resource with this name already exists."""
    data = api_request("GET", f"/{resource_type}?limit=50")
    for item in data or []:
        resource = item.get("postgres") or item.get("service") or item
        if resource.get("name") == name:
            return resource
    return None


def create_database():
    """
    Create the managed Postgres database.

    Returns the database ID and connection string (internal URL for
    service-to-service communication within Render's network).
    """
    print("\n=== Step 1: Create Postgres Database ===")

    # Check if it already exists
    existing = find_existing("postgres", DB_NAME)
    if existing:
        db_id = existing["id"]
        print(f"  Database '{DB_NAME}' already exists (ID: {db_id})")
        return db_id

    # Create the database
    print(f"  Creating database '{DB_NAME}'...")
    result = api_request("POST", "/postgres", {
        "databaseName": "golteris",
        "databaseUser": "golteris",
        "name": DB_NAME,
        "ownerId": OWNER_ID,
        "plan": PLAN,
        "region": REGION,
        "version": "16",
    })

    db_id = result["id"]
    print(f"  Created! ID: {db_id}")

    # Wait for the database to be available
    wait_for_status("postgres", db_id, "available")
    print("  Database is ready!")
    return db_id


def get_db_connection_info(db_id):
    """
    Retrieve the internal and external connection strings for the database.

    We use the internal URL for services running on Render (faster, no public
    internet hop). The external URL is for local development and debugging.

    Uses the /postgres/{id}/connection-info endpoint which returns the actual
    connection strings (the main /postgres/{id} endpoint doesn't include them).
    """
    print("\n=== Step 2: Get Database Connection Info ===")
    data = api_request("GET", f"/postgres/{db_id}/connection-info")

    internal_db_url = data.get("internalConnectionString", "")
    external_db_url = data.get("externalConnectionString", "")

    if internal_db_url:
        print(f"  Internal URL: {internal_db_url[:60]}...")
    if external_db_url:
        print(f"  External URL: {external_db_url[:60]}...")

    return internal_db_url, external_db_url


def create_web_service(internal_db_url):
    """
    Create the web service that runs FastAPI + serves the React build.

    The service is configured to:
    - Build from the Dockerfile in the repo root
    - Auto-deploy on every push to master
    - Use the internal Postgres connection string (passed directly, not via
      fromDatabase — the Render API doesn't support fromDatabase references)
    - Health check on /health
    """
    print("\n=== Step 3: Create Web Service ===")

    existing = find_existing("services", WEB_NAME)
    if existing:
        svc_id = existing["id"]
        url = existing.get("serviceDetails", {}).get("url", "unknown")
        print(f"  Web service '{WEB_NAME}' already exists (ID: {svc_id})")
        print(f"  URL: {url}")
        return svc_id, url

    print(f"  Creating web service '{WEB_NAME}'...")
    result = api_request("POST", "/services", {
        "autoDeploy": "yes",
        "branch": BRANCH,
        "name": WEB_NAME,
        "ownerId": OWNER_ID,
        "repo": REPO_URL,
        "type": "web_service",
        "serviceDetails": {
            "env": "docker",
            "envSpecificDetails": {
                "dockerfilePath": "./Dockerfile",
                "dockerContext": ".",
            },
            "healthCheckPath": "/health",
            "plan": PLAN,
            "region": REGION,
        },
        "envVars": [
            {
                "key": "DATABASE_URL",
                "value": internal_db_url,
            },
            {
                "key": "ANTHROPIC_API_KEY",
                "value": ANTHROPIC_API_KEY,
            },
            {
                "key": "ANTHROPIC_DAILY_COST_CAP",
                "value": "50.00",
            },
            {
                "key": "ANTHROPIC_MONTHLY_COST_CAP",
                "value": "500.00",
            },
        ],
    })

    service = result.get("service", result)
    svc_id = service["id"]
    url = service.get("serviceDetails", {}).get("url", "pending...")
    print(f"  Created! ID: {svc_id}")
    print(f"  URL: {url}")
    return svc_id, url


def create_worker_service(internal_db_url):
    """
    Create the background worker that processes the job queue.

    The worker runs backend/worker.py as a long-lived process.
    C1 enforcement: it checks workflows.enabled before dispatching jobs.
    """
    print("\n=== Step 4: Create Worker Service ===")

    existing = find_existing("services", WORKER_NAME)
    if existing:
        svc_id = existing["id"]
        print(f"  Worker '{WORKER_NAME}' already exists (ID: {svc_id})")
        return svc_id

    print(f"  Creating worker '{WORKER_NAME}'...")
    result = api_request("POST", "/services", {
        "autoDeploy": "yes",
        "branch": BRANCH,
        "name": WORKER_NAME,
        "ownerId": OWNER_ID,
        "repo": REPO_URL,
        "type": "background_worker",
        "serviceDetails": {
            "env": "docker",
            "envSpecificDetails": {
                "dockerfilePath": "./Dockerfile",
                "dockerContext": ".",
                "dockerCommand": "python -m backend.worker",
            },
            "plan": PLAN,
            "region": REGION,
        },
        "envVars": [
            {
                "key": "DATABASE_URL",
                "value": internal_db_url,
            },
            {
                "key": "ANTHROPIC_API_KEY",
                "value": ANTHROPIC_API_KEY,
            },
            {
                "key": "ANTHROPIC_DAILY_COST_CAP",
                "value": "50.00",
            },
            {
                "key": "ANTHROPIC_MONTHLY_COST_CAP",
                "value": "500.00",
            },
            {
                "key": "WORKER_POLL_INTERVAL",
                "value": "10",
            },
        ],
    })

    service = result.get("service", result)
    svc_id = service["id"]
    print(f"  Created! ID: {svc_id}")
    return svc_id


def main():
    """
    Main entry point — provisions the full Golteris stack on Render.

    Steps:
    1. Create Postgres database (or find existing)
    2. Get the database connection info
    3. Create the web service (FastAPI + React)
    4. Create the worker service (job queue processor)
    5. Print summary with URLs and next steps
    """
    print("=" * 60)
    print("Golteris — Render Infrastructure Setup")
    print("=" * 60)

    # Validate required config
    if not RENDER_API_KEY:
        print("ERROR: RENDER_API_KEY not set. Add it to .env or set the environment variable.")
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        print("WARNING: ANTHROPIC_API_KEY not set. The services will be created but Claude calls won't work.")

    # Step 1: Database
    db_id = create_database()

    # Step 2: Connection info
    internal_url, external_url = get_db_connection_info(db_id)

    # Step 3: Web service (pass internal DB URL directly — the Render API
    # doesn't support fromDatabase references like render.yaml does)
    web_id, web_url = create_web_service(internal_url)

    # Step 4: Worker
    worker_id = create_worker_service(internal_url)

    # Summary
    print("\n" + "=" * 60)
    print("SETUP COMPLETE")
    print("=" * 60)
    print(f"\n  Postgres:  {db_id}")
    print(f"  Web:       {web_id}")
    print(f"  Worker:    {worker_id}")
    print(f"\n  Live URL:  {web_url}")
    print(f"  Health:    {web_url}/health")
    print(f"  API Docs:  {web_url}/docs")
    if external_url:
        print(f"\n  External DB URL (for local dev):")
        print(f"    {external_url}")
    print("\n  Next steps:")
    print("  1. Wait 2-3 minutes for the first deploy to finish")
    print(f"  2. Visit {web_url}/health to verify")
    print("  3. Check Render dashboard for deploy logs if something fails")
    print(f"  4. Update .env with DATABASE_URL for local dev")


if __name__ == "__main__":
    main()
