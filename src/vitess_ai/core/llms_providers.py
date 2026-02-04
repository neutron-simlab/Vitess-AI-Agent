"""
LLM Provider Factory and Utilities
Centralized LLM provider management for OpenAI, Blablador, and future Anthropic
"""
from typing import Dict
from langchain_openai import ChatOpenAI
from vitess_ai.schema.llm_models import BlabladorModelName, Provider


def _get_config():
    """Lazy import of global_config to avoid circular import"""
    from vitess_ai.core.config import global_config
    return global_config


class LLMFactory:
    """Factory for creating LLM instances with different providers"""
    
    @staticmethod
    def create_llm(
        provider: str = None,
        model: str = None,
        temperature: float = 0.0,
        **kwargs
    ) -> ChatOpenAI:
        """
        Create LLM instance based on provider
        
        Args:
            provider: 'openai' and 'blablador'
            model: Model name (provider-specific)
            temperature: Temperature setting
            **kwargs: Provider-specific parameters
        
        Returns:
            ChatOpenAI instance
        """
        
        # Use config defaults if not specified
        config = _get_config()
        provider = provider or config.DEFAULT_PROVIDER
        model = model or config.DEFAULT_MODEL
        
        if provider.lower() == 'openai':
            return LLMFactory._create_openai(model, temperature, **kwargs)
        elif provider.lower() == 'blablador':
            return LLMFactory._create_blablador(model, temperature, **kwargs)
        else:
            raise ValueError(f"Unsupported provider: {provider}. Available: openai and blablador")
    
    @staticmethod
    def _create_openai(model: str, temperature: float, **kwargs) -> ChatOpenAI:
        """Create OpenAI LLM"""
        config = _get_config()
        llm_kwargs = {
            'api_key': config.OPENAI_API_KEY,
            'model': model,
            'temperature': temperature,
            'max_tokens': kwargs.get('max_tokens', config.MAX_TOKENS),
            'timeout': kwargs.get('timeout', config.TIMEOUT_SECONDS),
            'max_retries': kwargs.get('max_retries', config.MAX_RETRIES),
        }
        # Only set streaming if explicitly provided in kwargs
        if 'streaming' in kwargs:
            llm_kwargs['streaming'] = kwargs['streaming']
        return ChatOpenAI(**llm_kwargs)
    
    @staticmethod
    def _create_blablador(model: str, temperature: float, **kwargs) -> ChatOpenAI:
        """Create Blablador LLM (uses ChatOpenAI with custom base_url)
        
        Note: timeout is properly configured here to prevent hanging.
        The timeout value (default 60s from config.TIMEOUT_SECONDS) 
        is passed to ChatOpenAI which will raise a timeout error if exceeded.
        """
        config = _get_config()
        timeout = kwargs.get('timeout', config.TIMEOUT_SECONDS)
        llm_kwargs = {
            'api_key': config.BLABLADOR_API_KEY,
            'base_url': config.BLABLADOR_BASE_URL,
            'model': model,
            'temperature': temperature,
            'max_tokens': kwargs.get('max_tokens', config.MAX_TOKENS),
            'timeout': timeout,  # Timeout in seconds - prevents hanging on Blablador
            'max_retries': kwargs.get('max_retries', config.MAX_RETRIES),
        }
        # Only set streaming if explicitly provided in kwargs
        if 'streaming' in kwargs:
            llm_kwargs['streaming'] = kwargs['streaming']
        return ChatOpenAI(**llm_kwargs)


def create_llm_with_fallback(
    provider: str = None, 
    model: str = None, 
    temperature: float = 0.0,
    **kwargs
) -> ChatOpenAI:
    """
    Create LLM with automatic fallback to available providers.
    
    Fallback chain is built dynamically from available providers only,
    making it future-proof for new providers (Gemini, Anthropic, etc.).
    """
    
    # Use config defaults if not specified
    config = _get_config()
    provider = provider or config.DEFAULT_PROVIDER
    model = model or config.DEFAULT_MODEL
    
    try:
        return LLMFactory.create_llm(provider, model, temperature, **kwargs)
    except Exception as e:
        print(f"⚠️ {provider} failed: {e}")
        
        # Build fallback chain dynamically from available providers
        available_providers = get_available_providers()
        
        # Get list of available provider names (sorted for consistent fallback order)
        fallback_chain = [
            p.value for p in Provider 
            if available_providers.get(p.value, False) and p.value != provider.lower()
        ]
        
        if not fallback_chain:
            raise Exception(
                f"Provider {provider} failed and no fallback providers are available. "
                f"Please configure at least one provider with valid API keys."
            )
        
        for fallback_provider in fallback_chain:
            print(f"🔄 Trying fallback: {fallback_provider}")
            try:
                return LLMFactory.create_llm(fallback_provider, model, temperature, **kwargs)
            except Exception as fallback_error:
                print(f"❌ {fallback_provider} also failed: {fallback_error}")
                continue
        
        raise Exception(f"All available providers failed. Last error: {e}")


def get_available_providers() -> Dict[str, bool]:
    """
    Check which providers are available (have API keys configured)
    
    This function delegates to Config.get_available_providers() to avoid code duplication.
    The actual implementation is in config.py to avoid circular imports.
    
    Returns:
        Dict mapping provider names to availability status
    """
    config = _get_config()
    return config.get_available_providers()


def get_available_models(provider: str) -> list[str]:
    """
    Get list of available models for a provider based on .env configuration.
    
    If provider-specific AVAILABLE_MODELS env var is set, returns that filtered list.
    Otherwise, returns all models from the enum for that provider.
    
    Args:
        provider: Provider name ('openai' or 'blablador')
        
    Returns:
        List of available model names for the provider
    """
    config = _get_config()
    return config.get_available_models(provider)


def validate_provider_config(provider: str) -> bool:
    """
    Validate that a specific provider is properly configured
    
    Args:
        provider: Provider name to validate
        
    Returns:
        True if provider is configured and available
    """
    available = get_available_providers()
    return available.get(provider.lower(), False)


def create_supervisor_llm(
    provider: str = None,
    model: str = None,
    **kwargs
) -> ChatOpenAI:
    """
    Create LLM specifically configured for supervisor agent
    
    Args:
        provider: LLM provider
        model: Model name (uses supervisor-optimized model if None)
        **kwargs: Additional parameters
        
    Returns:
        ChatOpenAI configured for supervisor use
    """
    
    # Use supervisor-specific defaults
    config = _get_config()
    provider = provider or config.DEFAULT_PROVIDER
    
    return create_llm_with_fallback(
        provider=provider,
        model=model,
        temperature=0.0,  # Supervisor needs consistent behavior
        **kwargs
    )


def create_module_agent_llm(
    provider: str = None,
    model: str = None,
    **kwargs
) -> ChatOpenAI:
    """
    Create LLM specifically configured for module agents
    
    Args:
        provider: LLM provider  
        model: Model name (uses module-optimized model if None)
        **kwargs: Additional parameters
        
    Returns:
        ChatOpenAI configured for module agent use
    """
    
    # Use module-specific defaults
    config = _get_config()
    provider = provider or config.DEFAULT_PROVIDER
    
    return create_llm_with_fallback(
        provider=provider,
        model=model,
        temperature=0.0,  # Modules need consistent parameter generation
        **kwargs
    )


# =================
# PROVIDER TESTING UTILITIES
# =================

def test_provider_connection(provider: str, model: str = None) -> bool:
    """
    Test if a provider connection works
    
    Args:
        provider: Provider to test
        model: Model to test (uses default if None)
        
    Returns:
        True if connection successful, False otherwise
    """
    try:
        # Get recommended model if none specified
        
        # Create LLM instance
        llm = LLMFactory.create_llm(provider=provider, model=model)
        
        # Test with simple invocation
        from langchain_core.messages import HumanMessage
        test_message = [HumanMessage(content="Hello, respond with just 'OK'")]
        response = llm.invoke(test_message)
        
        return bool(response.content and len(response.content.strip()) > 0)
        
    except Exception as e:
        print(f"❌ Provider {provider} test failed: {e}")
        return False


def test_all_available_providers() -> Dict[str, bool]:
    """
    Test all configured providers
    
    Returns:
        Dict mapping provider names to test results
    """
    available = get_available_providers()
    results = {}
    
    print("🧪 Testing provider connections...")
    
    for provider, is_configured in available.items():
        if is_configured:
            print(f"  Testing {provider}...")
            # Use default model for each provider
            config = _get_config()
            model = config.DEFAULT_MODEL
            results[provider] = test_provider_connection(provider, model)
            status = "✅ Working" if results[provider] else "❌ Failed"
            print(f"  {provider}: {status}")
        else:
            print(f"  Skipping {provider} (not configured)")
            results[provider] = False
    
    return results



# =================
# BLABLADOR SPECIFIC UTILITIES
# =================

def test_blablador_connection() -> bool:
    """Specifically test Blablador connection"""
    if not validate_provider_config('blablador'):
        print("❌ Blablador not configured")
        return False
    
    print("🧪 Testing Blablador connection...")
    try:
        llm = LLMFactory.create_llm('blablador', BlabladorModelName.GPT_OSS.value)
        from langchain_core.messages import HumanMessage
        response = llm.invoke([HumanMessage(content="Hello")])
        print(f"✅ Blablador working: {response.content[:50]}...")
        return True
    except Exception as e:
        print(f"❌ Blablador test failed: {e}")
        return False


    