"""
LLM Provider Factory and Utilities
Centralized LLM provider management for OpenAI, Blablador, and future Anthropic
"""
from typing import Dict
from langchain_openai import ChatOpenAI
from vitess_ai.core.config import global_config


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
        provider = provider or global_config.DEFAULT_PROVIDER
        model = model or global_config.DEFAULT_MODEL
        
        if provider.lower() == 'openai':
            return LLMFactory._create_openai(model, temperature, **kwargs)
        elif provider.lower() == 'blablador':
            return LLMFactory._create_blablador(model, temperature, **kwargs)
        else:
            raise ValueError(f"Unsupported provider: {provider}. Available: openai and blablador")
    
    @staticmethod
    def _create_openai(model: str, temperature: float, **kwargs) -> ChatOpenAI:
        """Create OpenAI LLM"""
        return ChatOpenAI(
            api_key=global_config.OPENAI_API_KEY,
            model=model,
            temperature=temperature,
            max_tokens=kwargs.get('max_tokens', global_config.MAX_TOKENS),
            timeout=kwargs.get('timeout', global_config.TIMEOUT_SECONDS),
            max_retries=kwargs.get('max_retries', global_config.MAX_RETRIES)
        )
    
    @staticmethod
    def _create_blablador(model: str, temperature: float, **kwargs) -> ChatOpenAI:
        """Create Blablador LLM (uses ChatOpenAI with custom base_url)"""
        return ChatOpenAI(
            api_key=global_config.BLABLADOR_API_KEY,
            base_url=global_config.BLABLADOR_BASE_URL,
            model=model,
            temperature=temperature,
            max_tokens=kwargs.get('max_tokens', global_config.MAX_TOKENS),
            timeout=kwargs.get('timeout', global_config.TIMEOUT_SECONDS),
            max_retries=kwargs.get('max_retries', global_config.MAX_RETRIES)
        )


def create_llm_with_fallback(
    provider: str = None, 
    model: str = None, 
    temperature: float = 0.0,
    **kwargs
) -> ChatOpenAI:
    """
    Create LLM with automatic fallback to available providers
    Priority: OpenAI -> Blablador 
    """
    
    # Use global_config defaults if not specified
    provider = provider or global_config.DEFAULT_PROVIDER
    model = model or global_config.DEFAULT_MODEL
    
    try:
        return LLMFactory.create_llm(provider, model, temperature, **kwargs)
    except Exception as e:
        print(f"⚠️ {provider} failed: {e}")
        
        # Try fallback chain: OpenAI -> Blablador
        fallback_chain = ['openai', 'blablador']
        
        # Remove the failed provider from fallback chain
        if provider.lower() in fallback_chain:
            fallback_chain.remove(provider.lower())
        
        for fallback_provider in fallback_chain:
            if get_available_providers().get(fallback_provider, False):
                print(f"🔄 Trying fallback: {fallback_provider}")
                try:
                    return LLMFactory.create_llm(fallback_provider, model, temperature, **kwargs)
                except Exception as fallback_error:
                    print(f"❌ {fallback_provider} also failed: {fallback_error}")
                    continue
        
        raise Exception(f"All providers failed. Last error: {e}")


def get_available_providers() -> Dict[str, bool]:
    """
    Check which providers are available (have API keys configured)
    
    Returns:
        Dict mapping provider names to availability status
    """
    providers = {
        'openai': bool(global_config.OPENAI_API_KEY),
        'blablador': bool(global_config.BLABLADOR_API_KEY and global_config.BLABLADOR_BASE_URL)
        # 'anthropic': bool(global_config.ANTHROPIC_API_KEY),
    }
    return providers


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
    provider = provider or global_config.DEFAULT_PROVIDER
    
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
    provider = provider or global_config.DEFAULT_PROVIDER
    
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
        llm = LLMFactory.create_llm('blablador', 'alias-fast')
        from langchain_core.messages import HumanMessage
        response = llm.invoke([HumanMessage(content="Hello")])
        print(f"✅ Blablador working: {response.content[:50]}...")
        return True
    except Exception as e:
        print(f"❌ Blablador test failed: {e}")
        return False


# =================
# EXAMPLE USAGE
# =================

if __name__ == "__main__":
    """Example usage of LLM providers"""
    
    # Test creating different LLMs
    try:
        print("\n🧪 Testing LLM creation...")
        
        # Test OpenAI if available
        if validate_provider_config('openai'):
            openai_llm = create_supervisor_llm(provider='openai')
            print(f"✅ OpenAI supervisor LLM created")
        
        # Test Blablador if available  
        if validate_provider_config('blablador'):
            blablador_llm = create_module_agent_llm(provider='blablador', model='alias-fast-experimental')
            print(f"✅ Blablador module LLM created")
        
        # Test fallback
        fallback_llm = create_llm_with_fallback()
        print(f"✅ Fallback LLM created")
        
    except Exception as e:
        print(f"❌ Testing failed: {e}")
    
    # Test all providers
    print("\n🔍 Testing Blablador connection...")
    test_results = test_blablador_connection()
    