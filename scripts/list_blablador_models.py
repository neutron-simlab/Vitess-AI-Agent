#!/usr/bin/env python3
"""
Script to list all available models deployed in Blablador.

This script queries the Blablador API (OpenAI-compatible) to retrieve
and display all available models.

Usage:
    python scripts/list_blablador_models.py
    
    Options:
        --json, -j    Show raw JSON response
        --verbose, -v Show all fields for each model (useful for debugging)
    
    Or make it executable:
    chmod +x scripts/list_blablador_models.py
    ./scripts/list_blablador_models.py
"""

import sys
import os
import json
import re
from pathlib import Path

# Add project root to path to import vitess_ai modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import httpx
except ImportError:
    print("❌ Error: 'httpx' library not found.")
    print("   Install it with: pip install httpx")
    print("   Or use uv: uv pip install httpx")
    sys.exit(1)

from vitess_ai.core.config import global_config


def list_blablador_models() -> dict:
    """
    Query Blablador API to get list of available models.
    
    Returns:
        Dictionary with API response containing models list
    """
    # Check if Blablador is configured
    if not global_config.BLABLADOR_API_KEY:
        raise ValueError("BLABLADOR_API_KEY is not configured. Please set it in your .env file.")
    
    if not global_config.BLABLADOR_BASE_URL:
        raise ValueError("BLABLADOR_BASE_URL is not configured. Please set it in your .env file.")
    
    # Construct the models endpoint URL
    base_url = global_config.BLABLADOR_BASE_URL.rstrip('/')
    models_url = f"{base_url}/models"
    
    # Make the request
    headers = {
        "Authorization": f"Bearer {global_config.BLABLADOR_API_KEY}",
        "Content-Type": "application/json"
    }
    
    print(f"🔍 Querying Blablador API at: {models_url}")
    print(f"   Using API key: {global_config.BLABLADOR_API_KEY[:10]}...")
    print()
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(models_url, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_msg = f"API Error ({e.response.status_code}): {e.response.text}"
        raise Exception(error_msg) from e
    except httpx.RequestError as e:
        error_msg = f"Request failed: {str(e)}"
        raise Exception(error_msg) from e


def get_model_details(model_id: str, base_url: str, headers: dict) -> dict:
    """
    Query detailed information about a specific model.
    Tries multiple endpoints that might provide model details.
    
    Args:
        model_id: The model ID to query
        base_url: Base URL for the API
        headers: Request headers
        
    Returns:
        Dictionary with model details or empty dict if not available
    """
    # Try multiple possible endpoints
    endpoints_to_try = [
        f"{base_url}/models/{model_id}",  # Standard individual model endpoint
        f"{base_url}/v1/models/{model_id}",  # With v1 prefix
        f"{base_url}/model/{model_id}",  # Alternative endpoint
        f"{base_url}/models/{model_id}/info",  # Info endpoint
    ]
    
    for endpoint in endpoints_to_try:
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(endpoint, headers=headers)
                if response.status_code == 200:
                    result = response.json()
                    # If it's a dict with 'data' key, return the data
                    if isinstance(result, dict) and 'data' in result:
                        return result['data']
                    return result
        except Exception:
            continue
    
    return {}


def format_models_output(data: dict, base_url: str = None, headers: dict = None) -> str:
    """
    Format the models data into a readable output.
    
    Args:
        data: API response dictionary
        base_url: Base URL for querying model details (optional)
        headers: Request headers for querying model details (optional)
        
    Returns:
        Formatted string with model information
    """
    output_lines = []
    
    if 'data' not in data:
        return json.dumps(data, indent=2)
    
    models = data['data']
    
    if not models:
        return "⚠️  No models found in Blablador."
    
    output_lines.append(f"✅ Found {len(models)} model(s) in Blablador:\n")
    
    # Sort models by ID for consistent output
    models_sorted = sorted(models, key=lambda x: x.get('id', ''))
    
    # Separate aliases from actual models
    alias_models = []
    actual_models = []
    
    for model in models_sorted:
        model_id = model.get('id', '')
        if model_id.startswith('alias-'):
            alias_models.append(model)
        else:
            actual_models.append(model)
    
    # Display alias models first with emphasis on underlying model
    if alias_models:
        output_lines.append("=" * 70)
        output_lines.append("ALIAS MODELS (pointers to underlying models)")
        output_lines.append("=" * 70)
        output_lines.append("")
        
        for i, model in enumerate(alias_models, 1):
            model_id = model.get('id', 'N/A')
            model_object = model.get('object', 'N/A')
            created = model.get('created', 'N/A')
            owned_by = model.get('owned_by', 'N/A')
            
            output_lines.append(f"{i}. Alias: {model_id}")
            output_lines.append(f"   Type: {model_object}")
            
            # Look for fields that might indicate the underlying model
            # Check multiple possible field names that APIs might use
            underlying_model = None
            
            # Common field names for underlying/base model
            possible_fields = [
                'parent', 'base_model', 'model', 'source_model', 
                'target_model', 'aliases', 'alias_of', 'points_to'
            ]
            
            for field in possible_fields:
                value = model.get(field)
                if value:
                    if isinstance(value, str):
                        underlying_model = value
                        break
                    elif isinstance(value, list) and len(value) > 0:
                        underlying_model = value[0] if isinstance(value[0], str) else str(value[0])
                        break
                    elif isinstance(value, dict):
                        # If it's a dict, try common keys
                        underlying_model = value.get('id') or value.get('model') or value.get('name')
                        if underlying_model:
                            break
            
            # Check permission objects (OpenAI format sometimes has this)
            if not underlying_model and 'permission' in model:
                perms = model.get('permission', [])
                if isinstance(perms, list) and len(perms) > 0:
                    perm = perms[0]
                    if isinstance(perm, dict):
                        underlying_model = perm.get('id') or perm.get('model') or perm.get('name')
            
            # Try to get detailed info from individual model endpoint if available
            if not underlying_model and base_url and headers:
                details = get_model_details(model_id, base_url, headers)
                if details:
                    # Check all fields in details
                    for field in possible_fields:
                        value = details.get(field)
                        if value:
                            if isinstance(value, str):
                                underlying_model = value
                                break
                            elif isinstance(value, list) and len(value) > 0:
                                underlying_model = value[0] if isinstance(value[0], str) else str(value[0])
                                break
                    
                    # If still not found, check if details itself has useful info
                    if not underlying_model:
                        # Sometimes the details dict itself contains the model info
                        details_id = details.get('id')
                        if details_id and not details_id.startswith('alias-'):
                            # This might be the underlying model
                            underlying_model = details_id
                        # Or check for nested structures
                        elif 'model' in str(details).lower():
                            # Try to find any model-like string in the details
                            import re
                            details_str = json.dumps(details)
                            # Look for patterns like model names (not aliases)
                            model_patterns = re.findall(r'"[^"]*/(?:[^"]*)"', details_str)
                            for pattern in model_patterns:
                                clean_pattern = pattern.strip('"')
                                if not clean_pattern.startswith('alias-'):
                                    underlying_model = clean_pattern
                                    break
            
            if underlying_model:
                output_lines.append(f"   ⚡ Underlying Model: {underlying_model}")
            else:
                output_lines.append(f"   ⚠️  Underlying Model: Not found in API response")
                output_lines.append(f"      Tip: Use --json flag to see all fields in the response")
                # Try to show all model fields to help identify where the info might be
                if '--verbose' in sys.argv or '-v' in sys.argv:
                    output_lines.append(f"      All model fields: {json.dumps(model, indent=10)}")
            
            if created != 'N/A':
                try:
                    from datetime import datetime
                    created_date = datetime.fromtimestamp(created).strftime('%Y-%m-%d %H:%M:%S')
                    output_lines.append(f"   Created: {created_date}")
                except (ValueError, TypeError, OSError):
                    output_lines.append(f"   Created: {created}")
            
            output_lines.append(f"   Owned by: {owned_by}")
            
            # Show all fields for debugging (excluding already shown fields)
            excluded_fields = ['id', 'object', 'created', 'owned_by']
            all_fields = {k: v for k, v in model.items() if k not in excluded_fields}
            if all_fields:
                output_lines.append(f"   Additional fields: {json.dumps(all_fields, indent=6)}")
            
            output_lines.append("")
    
    # Display actual models
    if actual_models:
        output_lines.append("=" * 70)
        output_lines.append("ACTUAL MODELS (non-aliases)")
        output_lines.append("=" * 70)
        output_lines.append("")
        
        for i, model in enumerate(actual_models, 1):
            model_id = model.get('id', 'N/A')
            model_object = model.get('object', 'N/A')
            created = model.get('created', 'N/A')
            owned_by = model.get('owned_by', 'N/A')
            
            output_lines.append(f"{i}. Model ID: {model_id}")
            output_lines.append(f"   Type: {model_object}")
            if created != 'N/A':
                try:
                    from datetime import datetime
                    created_date = datetime.fromtimestamp(created).strftime('%Y-%m-%d %H:%M:%S')
                    output_lines.append(f"   Created: {created_date}")
                except (ValueError, TypeError, OSError):
                    output_lines.append(f"   Created: {created}")
            output_lines.append(f"   Owned by: {owned_by}")
            
            # Add any additional fields
            additional_fields = {k: v for k, v in model.items() 
                               if k not in ['id', 'object', 'created', 'owned_by']}
            if additional_fields:
                output_lines.append(f"   Additional info: {json.dumps(additional_fields, indent=6)}")
            
            output_lines.append("")
    
    return "\n".join(output_lines)


def main():
    """Main function to run the script."""
    try:
        # Query Blablador for models
        data = list_blablador_models()
        
        # Prepare headers and base_url for potential model detail queries
        base_url = global_config.BLABLADOR_BASE_URL.rstrip('/')
        headers = {
            "Authorization": f"Bearer {global_config.BLABLADOR_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Format and print output
        output = format_models_output(data, base_url=base_url, headers=headers)
        print(output)
        
        # Also print raw JSON if verbose flag is set
        if '--json' in sys.argv or '-j' in sys.argv:
            print("\n" + "="*60)
            print("Raw JSON Response:")
            print("="*60)
            print(json.dumps(data, indent=2))
        
        return 0
        
    except ValueError as e:
        print(f"❌ Configuration Error: {e}")
        print("\n💡 Tip: Make sure you have set BLABLADOR_API_KEY and BLABLADOR_BASE_URL")
        print("   in your .env file or environment variables.")
        return 1
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

