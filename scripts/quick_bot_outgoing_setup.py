#!/usr/bin/env python3
"""
Chatwoot Agent Bot URL Updater

This script updates the outgoing webhook URL for an agent bot in Chatwoot
using the Super Admin API. Configuration is loaded from environment variables.
"""

import os
import sys
import requests
from dotenv import load_dotenv
import json

def load_environment():
    """Load environment variables from .env file"""
    load_dotenv()
    
    required_vars = [
        'CHATWOOT_INSTANCE_URL',
        'CHATWOOT_SUPER_ADMIN_TOKEN',
        'AGENT_BOT_ID',
        'NEW_OUTGOING_URL'
    ]
    
    config = {}
    missing_vars = []
    
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            missing_vars.append(var)
        else:
            config[var] = value
    
    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("\nPlease create a .env file with the following variables:")
        print("CHATWOOT_INSTANCE_URL=https://your-chatwoot-instance.com")
        print("CHATWOOT_SUPER_ADMIN_TOKEN=your_super_admin_api_token")
        print("AGENT_BOT_ID=your_bot_id")
        print("NEW_OUTGOING_URL=https://your-new-webhook-url.com/webhook")
        sys.exit(1)
    
    return config

def get_current_bot_info(config):
    """Fetch current bot information"""
    url = f"{config['CHATWOOT_INSTANCE_URL']}/api/v1/accounts/2/agent_bots/{config['AGENT_BOT_ID']}"
    headers = {
        'api_access_token': config['CHATWOOT_SUPER_ADMIN_TOKEN'],
        'Content-Type': 'application/json'
    }
    
    print(f"DEBUG: GET URL: {url}")
    
    try:
        response = requests.get(url, headers=headers)
        print(f"DEBUG: Response status: {response.status_code}")
        print(f"DEBUG: Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            try:
                return response.json()
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON response: {e}")
                print(f"Raw response: {response.text[:500]}")
                return None
        else:
            print(f"HTTP Error: {response.status_code}")
            print(f"Response content: {response.text[:500]}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return None

def list_all_bots(config):
    """List all agent bots to help debug"""
    url = f"{config['CHATWOOT_INSTANCE_URL']}/api/v1/accounts/2/agent_bots"
    headers = {
        'api_access_token': config['CHATWOOT_SUPER_ADMIN_TOKEN'],
        'Content-Type': 'application/json'
    }
    
    print(f"DEBUG: LIST URL: {url}")
    
    try:
        response = requests.get(url, headers=headers)
        print(f"DEBUG: List response status: {response.status_code}")
        
        if response.status_code == 200:
            try:
                bots = response.json()
                print(f"Found {len(bots)} bot(s):")
                for bot in bots:
                    print(f"  - ID: {bot.get('id')}, Name: {bot.get('name')}, Outgoing URL: {bot.get('outgoing_url', 'Not set')}")
                return bots
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON response: {e}")
                print(f"Raw response: {response.text[:500]}")
                return None
        else:
            print(f"HTTP Error: {response.status_code}")
            print(f"Response content: {response.text[:500]}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return None

def update_bot_webhook_url(config):
    """Update the agent bot's outgoing webhook URL"""
    url = f"{config['CHATWOOT_INSTANCE_URL']}/api/v1/accounts/2/agent_bots/{config['AGENT_BOT_ID']}"
    headers = {
        'api_access_token': config['CHATWOOT_SUPER_ADMIN_TOKEN'],
        'Content-Type': 'application/json'
    }
    
    payload = {
        'outgoing_url': config['NEW_OUTGOING_URL']
    }
    
    print(f"DEBUG: PUT URL: {url}")
    print(f"DEBUG: Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.put(url, headers=headers, json=payload)
        print(f"DEBUG: Response status: {response.status_code}")
        print(f"DEBUG: Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            try:
                return response.json()
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON response: {e}")
                print(f"Raw response: {response.text[:500]}")
                return None
        else:
            print(f"HTTP Error: {response.status_code}")
            print(f"Response content: {response.text[:500]}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return None

def main():
    """Main function"""
    print("Chatwoot Agent Bot URL Updater")
    print("=" * 40)
    
    # Load configuration from environment
    config = load_environment()
    
    print(f"Chatwoot Instance: {config['CHATWOOT_INSTANCE_URL']}")
    print(f"Bot ID: {config['AGENT_BOT_ID']}")
    print(f"New Outgoing URL: {config['NEW_OUTGOING_URL']}")
    print()
    
    # First, list all bots to see what's available
    print("Listing all available bots...")
    bots = list_all_bots(config)
    
    if not bots:
        print("Failed to list bots. Check your API token and permissions.")
        return
    
    # Check if the specified bot ID exists
    target_bot = None
    for bot in bots:
        if str(bot.get('id')) == str(config['AGENT_BOT_ID']):
            target_bot = bot
            break
    
    if not target_bot:
        print(f"Bot with ID {config['AGENT_BOT_ID']} not found!")
        print("Available bot IDs:", [bot.get('id') for bot in bots])
        return
    
    print(f"\nTarget bot found: {target_bot.get('name')} (ID: {target_bot.get('id')})")
    current_url = target_bot.get('outgoing_url', 'Not set')
    print(f"Current outgoing URL: {current_url}")
    
    if current_url == config['NEW_OUTGOING_URL']:
        print("The outgoing URL is already set to the desired value.")
        return
    
    # Update the webhook URL
    print("\nUpdating bot webhook URL...")
    result = update_bot_webhook_url(config)
    
    if result:
        new_url = result.get('outgoing_url', 'Unknown')
        print(f"✅ Successfully updated outgoing URL to: {new_url}")
    else:
        print("❌ Failed to update bot webhook URL")
        sys.exit(1)

if __name__ == "__main__":
    main()