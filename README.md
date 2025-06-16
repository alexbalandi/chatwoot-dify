# Chatdify: Chatwoot-Dify AI Connector

**Chatdify** is a Python-based connector designed to integrate Chatwoot with Dify AI. It acts as a bridge, listening to events in Chatwoot and triggering Dify AI pipelines to automate and enhance customer interactions.

## ⚠️ Beta Notice

**Important:** This project is currently in **beta** and is **not recommended for production use**. Please use it at your own risk and expect potential issues or changes.

## Core Features

*   **Event-driven:** Listens to Chatwoot webhook events (e.g., new messages, conversation status changes).
*   **AI Processing:** Processes incoming messages and conversation context through Dify AI pipelines.
*   **Automated Responses:** Sends AI-generated responses back to Chatwoot conversations.
*   **Conversation Management:** Provides API endpoints to programmatically manage Chatwoot conversation attributes (status, priority, labels, custom fields, team assignment), often triggered by Dify.
*   **Asynchronous Operations:** Utilizes Celery for background task processing (e.g., Dify API calls).
*   **Persistent Storage:** Uses PostgreSQL to store mappings between Chatwoot and Dify conversations.
*   **Configurable:** Settings managed via environment variables.

## How It Works

1.  Chatwoot sends webhook events (e.g., a new customer message) to Chatdify.
2.  Chatdify identifies the event and relevant conversation data.
3.  It triggers a pre-configured Dify AI pipeline, passing the message and context.
4.  Dify processes the input and returns a response or performs actions.
5.  Chatdify sends Dify's response back to the Chatwoot conversation.
6.  Dify pipelines can also call back to Chatdify's API endpoints to update conversation details in Chatwoot (e.g., set status, assign to a team).

## Getting Started

### Prerequisites

*   Docker and Docker Compose
*   `uv` (Python package manager by Astral)

### Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/eremeye/chatdify
    cd chatdify
    ```

2.  **Install dependencies:**
    ```bash
    uv sync
    ```

3.  **Configure your environment:**
    Copy the example environment file and then edit `.env` to fill in your specific configurations:
    ```bash
    cp .env.example .env
    nano .env  # Or your preferred editor
    ```
    Key environment variables to configure in `.env`:
    *   `CHATWOOT_API_URL`: Your Chatwoot instance API URL.
    *   `CHATWOOT_API_KEY`: API key for the Agent Bot.
    *   `CHATWOOT_ADMIN_API_KEY`: API key with admin privileges (e.g., for managing teams, custom attributes, and required for fetching teams; the application uses admin headers for this purpose).
    *   `CHATWOOT_ACCOUNT_ID`: Your Chatwoot account ID.
    *   `DIFY_API_URL`: Your Dify API URL.
    *   `DIFY_API_KEY`: Your Dify pipeline/application API key.
    *   Database credentials (`POSTGRES_PASSWORD`).

4.  **Chatwoot Configuration:**
    *   In your Chatwoot Super Admin console, configure an **Agent Bot**.
    *   Set the Agent Bot's **Outgoing URL** (webhook URL) to:
        `https://<your-chatdify-domain>/api/v1/chatwoot-webhook`
    *   Ensure the Agent Bot is added to the inboxes you want it to interact with.

5.  **Dify Configuration:**
    *   In your Dify AI application/pipeline settings, if it needs to call back to Chatdify (e.g., to update conversation status), set an environment variable or parameter like `bridge_api_url` to:
        `https://<your-chatdify-domain>/api/v1`

6.  **Run the application with Docker:**
    ```bash
    docker-compose up -d
    ```
    (Use `docker-compose up` without `-d` to see logs in the foreground).

## Utility Scripts

The `notebooks/setup_chatwoot_config.ipynb` Jupyter notebook provides an example of how to programmatically set up Chatwoot custom attributes and commands using the API. This requires admin privileges for your Chatwoot API key.
