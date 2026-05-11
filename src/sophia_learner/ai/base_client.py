"""
AI Base Client - Abstract interface for LLM interaction

This module defines the abstract base class for all AI backend clients,
along with custom exceptions and helper methods for prompt formatting
and response validation.
"""

import json
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime

# Custom exceptions for AI client operations


class AIConnectionError(Exception):
    """Raised when unable to connect to the AI backend."""
    pass


class AITimeoutError(Exception):
    """Raised when AI request exceeds timeout limit."""
    pass


class AIResponseError(Exception):
    """Raised when AI response is malformed or invalid."""
    pass


class AIClient(ABC):
    """
    Abstract base class for LLM interaction backends.
    
    This class defines the interface that all AI client implementations
    must follow. It provides common functionality for prompt formatting,
    response validation, and JSON parsing.
    
    Subclasses must implement:
        - process_text(): Generate training samples from document text
        - health_check(): Verify backend availability
        - get_model_info(): Return model metadata
    """
    
    def __init__(self, prompt_template: Optional[str] = None, 
                 output_schema: Optional[Dict] = None,
                 max_retries: int = 3,
                 timeout: int = 30):
        """
        Initialize the AI client with common configuration.
        
        Args:
            prompt_template: Template string for formatting prompts
            output_schema: Expected JSON schema for response validation
            max_retries: Maximum number of retry attempts on failure
            timeout: Request timeout in seconds
        """
        self.prompt_template = prompt_template or self._get_default_template()
        self.output_schema = output_schema or self._get_default_schema()
        self.max_retries = max_retries
        self.timeout = timeout
        
    @abstractmethod
    def process_text(self, text: str, metadata: Optional[Dict] = None) -> List[Dict]:
        """
        Process extracted document text and generate training samples.
        
        Args:
            text: Extracted text from the document
            metadata: Optional metadata about the document (filename, type, etc.)
            
        Returns:
            List of training samples, each as a dictionary matching output_schema
            
        Raises:
            AIConnectionError: If unable to connect to backend
            AITimeoutError: If request exceeds timeout
            AIResponseError: If response is malformed or invalid
        """
        pass
    
    @abstractmethod
    def health_check(self) -> bool:
        """
        Check if the AI backend is reachable and responsive.
        
        Returns:
            True if backend is healthy, False otherwise
        """
        pass
    
    @abstractmethod
    def get_model_info(self) -> Dict:
        """
        Get information about the loaded/configured model.
        
        Returns:
            Dictionary with model name, version, context length, etc.
        """
        pass
    
    def format_prompt(self, content: str, template: Optional[str] = None) -> str:
        """
        Format a prompt template with document content and context.
        
        Supports both simple string formatting ({content}) and
        Jinja2-style templates if jinja2 is installed.
        
        Args:
            content: Document content to insert into template
            template: Optional custom template (uses self.prompt_template if None)
            
        Returns:
            Formatted prompt string
        """
        template_to_use = template or self.prompt_template
        
        # Prepare context with content and additional variables
        context = {
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'content_length': len(content),
            'word_count': len(content.split())
        }
        
        # Try Jinja2 if available (more powerful templating)
        try:
            from jinja2 import Template
            jinja_template = Template(template_to_use)
            return jinja_template.render(**context)
        except ImportError:
            # Fall back to simple string formatting
            try:
                return template_to_use.format(**context)
            except KeyError as e:
                # If formatting fails, try replacing with content directly
                if '{content}' in template_to_use:
                    return template_to_use.format(content=content)
                else:
                    # Simple replacement as last resort
                    return template_to_use.replace('{{content}}', content) \
                                          .replace('{content}', content)
    
    def validate_response(self, response: Dict, schema: Optional[Dict] = None) -> bool:
        """
        Validate that an AI response conforms to the expected schema.
        
        Args:
            response: Response dictionary to validate
            schema: Optional custom schema (uses self.output_schema if None)
            
        Returns:
            True if response is valid, False otherwise
        """
        schema_to_use = schema or self.output_schema
        
        if not schema_to_use:
            # No schema to validate against
            return True
        
        # Check required fields
        required_fields = schema_to_use.get('required', [])
        for field in required_fields:
            if field not in response:
                return False
        
        # Check field types if specified
        properties = schema_to_use.get('properties', {})
        for field, expected_type in properties.items():
            if field in response:
                actual_value = response[field]
                expected_type_name = expected_type.get('type') if isinstance(expected_type, dict) else None
                
                if expected_type_name == 'string' and not isinstance(actual_value, str):
                    return False
                elif expected_type_name == 'integer' and not isinstance(actual_value, int):
                    return False
                elif expected_type_name == 'array' and not isinstance(actual_value, list):
                    return False
                elif expected_type_name == 'object' and not isinstance(actual_value, dict):
                    return False
        
        # If response is a list of samples, validate each one
        if isinstance(response, list):
            for item in response:
                if not self.validate_response(item, schema_to_use):
                    return False
        
        return True
    
    def _parse_json_response(self, raw_response: str) -> Dict:
        """
        Safely extract JSON from LLM response that may contain markdown or extra text.
        
        The LLM might wrap JSON in markdown code blocks or add explanatory text.
        This method extracts the first valid JSON object or array it finds.
        
        Args:
            raw_response: Raw string response from AI
            
        Returns:
            Parsed JSON as dictionary
            
        Raises:
            AIResponseError: If no valid JSON can be extracted
        """
        if not raw_response or not isinstance(raw_response, str):
            raise AIResponseError("Empty or invalid response from AI")
        
        # Try to extract JSON from markdown code blocks
        # Pattern for ```json ... ``` or ``` ... ```
        json_patterns = [
            r'```json\s*([\s\S]*?)\s*```',  # ```json ... ```
            r'```\s*([\s\S]*?)\s*```',       # ``` ... ```
            r'\{[\s\S]*\}',                   # JSON object
            r'\[[\s\S]*\]',                   # JSON array
        ]
        
        for pattern in json_patterns:
            match = re.search(pattern, raw_response)
            if match:
                json_str = match.group(1) if match.lastindex else match.group(0)
                try:
                    parsed = json.loads(json_str.strip())
                    return parsed
                except json.JSONDecodeError:
                    continue
        
        # Try parsing the entire response as JSON
        try:
            return json.loads(raw_response.strip())
        except json.JSONDecodeError as e:
            raise AIResponseError(f"Failed to parse JSON from response: {e}\nResponse: {raw_response[:500]}")
    
    def _get_default_template(self) -> str:
        """
        Get the default prompt template for generating training samples.
        
        Returns:
            Default prompt template string
        """
        return """You are an AI training data generator. Your task is to create high-quality training samples from the provided document.

Document Content:
{content}

Instructions:
1. Read the document carefully
2. Generate question-answer pairs that test understanding of key concepts
3. Create instruction-output pairs for tasks the document describes
4. Extract important facts as standalone statements
5. Identify any call-to-action or decision points

For each training sample, provide:
- type: "qa", "instruction", "fact", or "summary"
- input: The question or instruction
- output: The expected response or answer
- difficulty: "easy", "medium", or "hard"
- topic: Main topic area covered

Generate 3-5 diverse training samples that would be useful for fine-tuning a language model.

Output format: JSON array of objects with fields: type, input, output, difficulty, topic

Example:
[
  {{
    "type": "qa",
    "input": "What is the main purpose of the document?",
    "output": "The main purpose is to explain...",
    "difficulty": "easy",
    "topic": "overview"
  }}
]

Generate samples now:"""
    
    def _get_default_schema(self) -> Dict:
        """
        Get the default output schema for training samples.
        
        Returns:
            Default JSON schema dictionary
        """
        return {
            "type": "array",
            "required": ["type", "input", "output"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["qa", "instruction", "fact", "summary", "conversation"]
                },
                "input": {"type": "string"},
                "output": {"type": "string"},
                "difficulty": {
                    "type": "string",
                    "enum": ["easy", "medium", "hard"]
                },
                "topic": {"type": "string"},
                "context": {"type": "string"}
            }
        }
    
    def _sanitize_text_for_prompt(self, text: str, max_length: int = 8000) -> str:
        """
        Sanitize and truncate text for inclusion in prompts.
        
        Args:
            text: Raw extracted text
            max_length: Maximum character length to include
            
        Returns:
            Sanitized and truncated text
        """
        # Remove excessive whitespace
        sanitized = re.sub(r'\n\s*\n', '\n\n', text)
        sanitized = re.sub(r'[ \t]+', ' ', sanitized)
        
        # Truncate if too long
        if len(sanitized) > max_length:
            # Try to truncate at sentence boundary
            truncated = sanitized[:max_length]
            last_period = truncated.rfind('.')
            if last_period > max_length * 0.8:
                truncated = truncated[:last_period + 1]
            sanitized = truncated + "\n...[content truncated due to length]"
        
        return sanitized.strip()
    
    def _retry_on_failure(self, func, *args, **kwargs):
        """
        Execute a function with retry logic for transient failures.
        
        Args:
            func: Function to execute
            *args, **kwargs: Arguments to pass to function
            
        Returns:
            Result of function call
            
        Raises:
            Exception: If all retries fail
        """
        import time
        
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except (AIConnectionError, AITimeoutError) as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    time.sleep(wait_time)
                    continue
                raise
            except Exception as e:
                # Don't retry on non-connection errors
                raise
        
        raise last_exception if last_exception else Exception("Unknown error in retry loop")
    
    def batch_process(self, texts: List[str], 
                      metadata_list: Optional[List[Dict]] = None,
                      batch_size: int = 5) -> List[List[Dict]]:
        """
        Process multiple documents in batches.
        
        Args:
            texts: List of document texts
            metadata_list: Optional list of metadata dicts (same length as texts)
            batch_size: Number of documents to process per batch
            
        Returns:
            List of sample lists, one per input document
        """
        if metadata_list is None:
            metadata_list = [None] * len(texts)
        
        results = []
        
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_metadata = metadata_list[i:i + batch_size]
            
            for text, metadata in zip(batch_texts, batch_metadata):
                try:
                    samples = self.process_text(text, metadata)
                    results.append(samples)
                except Exception as e:
                    # Log error and return empty list for failed documents
                    results.append([])
            
            # Small delay between batches to avoid overwhelming the backend
            if i + batch_size < len(texts):
                import time
                time.sleep(1)
        
        return results
    
    def __repr__(self) -> str:
        """String representation of the AI client."""
        return f"{self.__class__.__name__}(model={self.get_model_info().get('name', 'unknown')})"
