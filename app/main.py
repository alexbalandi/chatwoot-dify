import logging
import os

# Using explicit integrations for more control
from fastapi import FastAPI
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from .api import health, webhooks
from .api.chatwoot_actions import actions_router # Import the new actions_router
# The lifespan for team_cache is now part of actions_router
# from .api.webhooks import lifespan # This specific lifespan is removed from main app
from .database import async_engine, create_db_tables
from .telemetry import setup_telemetry
from .utils.sentry import init_sentry

# Add before creating FastAPI app
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Initialize Sentry with FastAPI, AsyncPG, and Celery integrations


# Initialize Sentry with configurable integrations
sentry_initialized = init_sentry(
    with_fastapi=True,
    with_asyncpg=True,
    with_celery=True,
    custom_integrations=[
        StarletteIntegration(
            transaction_style="endpoint",  # Use endpoint names for transactions
            failed_request_status_codes={*range(400, 600)},  # Capture 4xx and 5xx errors
        ),
        FastApiIntegration(
            transaction_style="endpoint",  # Use endpoint names for transactions
            failed_request_status_codes={*range(400, 600)},  # Capture 4xx and 5xx errors
        ),
    ],
)

if sentry_initialized:
    logging.info("Sentry initialized for FastAPI application with custom integration settings")

# Lifespan for team cache is now handled by actions_router.
# If there's other app-level startup/shutdown logic, a new lifespan function would be needed here.
app = FastAPI(title="Chatwoot AI Handler", debug=os.getenv("DEBUG", "False") == "True") # Removed lifespan=lifespan
setup_telemetry(app, async_engine)


# Initialize database tables asynchronously
@app.on_event("startup")
async def startup_db_client():
    await create_db_tables()


app.include_router(webhooks.router, prefix="/api/v1", tags=["Webhooks"]) # Added tags for better Swagger UI organization
app.include_router(actions_router, prefix="/api/v1/actions", tags=["Actions"]) # Include the new actions router
app.include_router(health.router, prefix="/api/v1/health", tags=["Health"])
