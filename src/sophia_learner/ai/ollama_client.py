"""
Ollama Client - Integration with local Ollama LLM backend

This module provides a client for interacting with Ollama's REST API,
supporting text generation for training data creation.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

import httpx

from .base_client import AIClient, AIConnectionError, AITimeoutError, AIResponseError
from ..utils.retry import retry
from ..utils.logger import get_logger

logger = get_logger(__name__)


class OllamaClient(AIClient):
    """
    Client for interacting with a local Ollama instance.
    
    This client communicates with Ollama's REST API to generate
    training samples from document text. It supports configurable
    model parameters and includes retry logic for transient failures.
    
    Attributes:
        base_url: Ollama API base URL (e.g., http://localhost:11434)
        model: Model name (e.g., "llama3.2:3b", "mistral:7b")
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature (0.0 to 1.0)
        timeout: Request timeout in seconds
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2:3b",
        timeout: int = 60,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        prompt_template: Optional[str] = None,
        output_schema: Optional[Dict] = None,
        max_retries: int = 3
    ):
        """
        Initialize the Ollama client.
        
        Args:
            base_url: Ollama API base URL
            model: Model name to use for generation
            timeout: Request timeout in seconds
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature (higher = more random)
            prompt_template: Optional custom prompt template
            output_schema: Optional custom output schema
            max_retries: Maximum retry attempts on failure
        """
        super().__init__(
            prompt_template=prompt_template,
            output_schema=output_schema,
            max_retries=max_retries,
            timeout=timeout
        )
        
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        
        # Create HTTP client with connection pooling
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            follow_redirects=True
        )
        
        logger.info(f"OllamaClient initialized: {base_url}, model={model}, "
                   f"max_tokens={max_tokens}, temperature={temperature}")
    
    def process_text(self, text: str, metadata: Optional[Dict] = None) -> List[Dict]:
        """
        Process document text and generate training samples via Ollama.
        
        Args:
            text: Extracted text from document
            metadata: Optional document metadata
            
        Returns:
            List of training samples as dictionaries
            
        Raises:
            AIConnectionError: If Ollama is not reachable
            AITimeoutError: If request times out
            AIResponseError: If response is malformed
        """
        # Format the prompt with document content
        prompt = self.format_prompt(text)
        
        # Add document context to prompt if metadata provided
        if metadata:
            context_str = f"\n\nDocument Metadata:\n"
            for key, value in metadata.items():
                if value and key not in ['content', 'text']:
                    context_str += f"- {key}: {value}\n"
            prompt = prompt + context_str
        
        try:
            # Call Ollama API with retry logic
            raw_response = self._call_api(prompt)
            
            # Parse JSON from response
            parsed_response = self._parse_json_response(raw_response)
            
            # Ensure response is a list
            if isinstance(parsed_response, dict):
                # Single sample response
                samples = [parsed_response]
            elif isinstance(parsed_response, list):
                samples = parsed_response
            else:
                raise AIResponseError(f"Unexpected response type: {type(parsed_response)}")
            
            # Validate each sample against schema
            valid_samples = []
            for sample in samples:
                if self.validate_response(sample):
                    # Add metadata to sample
                    if metadata:
                        sample['_source_metadata'] = {
                            'filename': metadata.get('filename'),
                            'document_type': metadata.get('mime_type'),
                            'processed_at': datetime.now().isoformat()
                        }
                    valid_samples.append(sample)
                else:
                    logger.warning(f"Invalid sample rejected: {sample}")
            
            if not valid_samples:
                raise AIResponseError("No valid samples generated")
            
            logger.info(f"Generated {len(valid_samples)} valid samples from {self.model}")
            return valid_samples
            
        except httpx.TimeoutException as e:
            logger.error(f"Ollama API timeout: {e}")
            raise AITimeoutError(f"Request to Ollama timed out after {self.timeout}s") from e
        except httpx.ConnectError as e:
            logger.error(f"Failed to connect to Ollama: {e}")
            raise AIConnectionError(f"Cannot connect to Ollama at {self.base_url}") from e
        except (json.JSONDecodeError, AIResponseError) as e:
            logger.error(f"Response parsing error: {e}")
            raise AIResponseError(f"Failed to parse Ollama response: {e}") from e
        except Exception as e:
            logger.exception(f"Unexpected error in Ollama processing: {e}")
            raise
    
    def health_check(self) -> bool:
        """
        Check if Ollama is running and the model is available.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            # Check API endpoint
            response = self._client.get(
                f"{self.base_url}/api/tags",
                timeout=5.0
            )
            
            if response.status_code != 200:
                logger.warning(f"Ollama health check failed with status {response.status_code}")
                return False
            
            # Check if our model is available
            data = response.json()
            models = data.get('models', [])
            model_available = any(m.get('name', '').startswith(self.model) for m in models)
            
            if not model_available:
                logger.warning(f"Model {self.model} not found in Ollama. Available: {[m.get('name') for m in models]}")
                return False
            
            return True
            
        except httpx.TimeoutException:
            logger.warning("Ollama health check timeout")
            return False
        except httpx.ConnectError:
            logger.warning(f"Cannot connect to Ollama at {self.base_url}")
            return False
        except Exception as e:
            logger.error(f"Ollama health check error: {e}")
            return False
    
    def get_model_info(self) -> Dict:
        """
        Get information about the loaded Ollama model.
        
        Returns:
            Dictionary with model information
        """
        try:
            # Try to get model info from Ollama
            response = self._client.post(
                f"{self.base_url}/api/show",
                json={"name": self.model},
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "name": self.model,
                    "backend": "ollama",
                    "version": data.get("details", {}).get("parent_model", "unknown"),
                    "context_length": data.get("model_info", {}).get("context_length", 4096),
                    "parameter_size": data.get("details", {}).get("parameter_size", "unknown"),
                    "quantization": data.get("details", {}).get("quantization_level", "unknown"),
                    "available": True
                }
            else:
                return {
                    "name": self.model,
                    "backend": "ollama",
                    "available": False,
                    "error": f"API returned {response.status_code}"
                }
                
        except Exception as e:
            logger.warning(f"Failed to get model info: {e}")
            return {
                "name": self.model,
                "backend": "ollama",
                "available": False,
                "error": str(e)
            }
    
    @retry(max_attempts=3, delay=1.0, backoff=2.0, 
           exceptions=(httpx.TimeoutException, httpx.ConnectError, AIConnectionError))
    def _call_api(self, prompt: str) -> str:
        """
        Call Ollama API with retry logic.
        
        Args:
            prompt: Formatted prompt to send to Ollama
            
        Returns:
            Raw response text from Ollama
            
        Raises:
            AIConnectionError: If API call fails after retries
            AITimeoutError: If request times out
        """
        # Prepare request payload
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": self.max_tokens,
                "temperature": self.temperature,
                "top_p": 0.9,
                "top_k": 40,
                "repeat_penalty": 1.1,
                "stop": ["</s>", "<|eot_id|>"]
            }
        }
        
        logger.debug(f"Calling Ollama API with model {self.model}, max_tokens={self.max_tokens}")
        
        # Make the request
        response = self._client.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout
        )
        
        # Check response status
        if response.status_code != 200:
            error_msg = f"Ollama API returned {response.status_code}: {response.text[:200]}"
            logger.error(error_msg)
            raise AIConnectionError(error_msg)
        
        # Parse response
        try:
            data = response.json()
            generated_text = data.get("response", "")
            
            if not generated_text:
                raise AIResponseError("Empty response from Ollama")
            
            # Log token usage if available
            eval_count = data.get("eval_count", 0)
            prompt_eval_count = data.get("prompt_eval_count", 0)
            logger.debug(f"Generated {eval_count} tokens (prompt: {prompt_eval_count} tokens)")
            
            return generated_text
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Ollama response: {e}")
            raise AIResponseError(f"Invalid JSON response: {e}")
    
    def generate_stream(self, prompt: str):
        """
        Generate streaming response from Ollama (for long-form content).
        
        This is a generator that yields chunks of the response as they arrive.
        
        Args:
            prompt: Formatted prompt
            
        Yields:
            Chunks of generated text
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "num_predict": self.max_tokens,
                "temperature": self.temperature
            }
        }
        
        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout
            ) as response:
                for chunk in response.iter_lines():
                    if chunk:
                        try:
                            data = json.loads(chunk)
                            if "response" in data:
                                yield data["response"]
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            raise
    
    def list_models(self) -> List[Dict]:
        """
        List all available models in Ollama.
        
        Returns:
            List of model information dictionaries
        """
        try:
            response = self._client.get(f"{self.base_url}/api/tags", timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                return data.get("models", [])
            else:
                logger.warning(f"Failed to list models: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []
    
    def pull_model(self, model_name: str, progress_callback=None) -> bool:
        """
        Pull a model from Ollama registry (download if not present).
        
        Args:
            model_name: Name of model to pull
            progress_callback: Optional callback for progress updates
            
        Returns:
            True if successful, False otherwise
        """
        try:
            payload = {"name": model_name}
            
            with self._client.stream(
                "POST",
                f"{self.base_url}/api/pull",
                json=payload,
                timeout=3600  # Long timeout for model download
            ) as response:
                for chunk in response.iter_lines():
                    if chunk:
                        try:
                            data = json.loads(chunk)
                            if progress_callback and "status" in data:
                                progress_callback(data)
                            if data.get("done", False):
                                logger.info(f"Model {model_name} pulled successfully")
                                return True
                        except json.JSONDecodeError:
                            continue
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to pull model {model_name}: {e}")
            return False
    
    def close(self):
        """Close the HTTP client session."""
        self._client.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure client is closed."""
        self.close()
    
    def __repr__(self) -> str:
        """String representation."""
        return f"OllamaClient(base_url={self.base_url}, model={self.model}, timeout={self.timeout})"
