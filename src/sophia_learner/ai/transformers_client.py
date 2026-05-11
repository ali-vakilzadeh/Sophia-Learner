"""
Transformers Client - Direct integration with Hugging Face Transformers

This module provides a client that loads Hugging Face models directly,
supporting both CPU and GPU inference with memory optimization options.
"""

import gc
import json
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    pipeline,
    BitsAndBytesConfig
)

from .base_client import AIClient, AIConnectionError, AITimeoutError, AIResponseError
from ..utils.logger import get_logger

logger = get_logger(__name__)


class TransformersClient(AIClient):
    """
    Client for directly loading and using Hugging Face Transformers models.
    
    This client loads models directly into memory, providing more control
    but requiring more resources. Supports CPU, GPU (CUDA), and MPS (Apple Silicon)
    devices, with optional 8-bit quantization for memory efficiency.
    
    Attributes:
        model_name: Hugging Face model name or path
        device: Device to use ("cuda", "cpu", "mps", or "auto")
        load_in_8bit: Whether to load model in 8-bit quantization
        model: Loaded model instance
        tokenizer: Loaded tokenizer instance
        pipeline: Optional text generation pipeline
    """
    
    def __init__(
        self,
        model_name: str = "meta-llama/Llama-2-7b-chat-hf",
        device: str = "auto",
        load_in_8bit: bool = False,
        load_in_4bit: bool = False,
        prompt_template: Optional[str] = None,
        output_schema: Optional[Dict] = None,
        max_new_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.95,
        top_k: int = 50,
        repetition_penalty: float = 1.1,
        **model_kwargs
    ):
        """
        Initialize the Transformers client and load the model.
        
        Args:
            model_name: Hugging Face model name or local path
            device: Device to use ("cuda", "cpu", "mps", "auto")
            load_in_8bit: Enable 8-bit quantization (reduces memory)
            load_in_4bit: Enable 4-bit quantization (even more memory efficient)
            prompt_template: Optional custom prompt template
            output_schema: Optional custom output schema
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
            top_k: Top-k sampling parameter
            repetition_penalty: Penalty for repetition
            **model_kwargs: Additional arguments passed to model loading
        """
        super().__init__(
            prompt_template=prompt_template,
            output_schema=output_schema,
            max_retries=1,  # Transformers doesn't need retries like API calls
            timeout=300  # Longer timeout for model inference
        )
        
        self.model_name = model_name
        self.device = self._get_device(device)
        self.load_in_8bit = load_in_8bit
        self.load_in_4bit = load_in_4bit
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.repetition_penalty = repetition_penalty
        self.model_kwargs = model_kwargs
        
        # These will be set during loading
        self.model = None
        self.tokenizer = None
        self.generation_pipeline = None
        
        # Load the model
        self._load_model()
        
        logger.info(f"TransformersClient initialized: {model_name}, device={self.device}, "
                   f"8bit={load_in_8bit}, 4bit={load_in_4bit}")
    
    def _get_device(self, device: str) -> str:
        """
        Determine the appropriate device for model loading.
        
        Args:
            device: Requested device or "auto"
            
        Returns:
            Actual device to use
        """
        if device != "auto":
            return device
        
        # Auto-detect best available device
        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            return "mps"
        else:
            return "cpu"
    
    def _load_model(self):
        """
        Load the model and tokenizer from Hugging Face.
        
        This method handles quantization configuration and device mapping
        to optimize memory usage.
        """
        try:
            logger.info(f"Loading model {self.model_name} on {self.device}...")
            
            # Configure quantization if requested
            quantization_config = None
            if self.load_in_8bit:
                quantization_config = BitsAndBytesConfig(
                    load_in_8bit=True,
                    llm_int8_threshold=6.0
                )
                logger.info("Using 8-bit quantization")
            elif self.load_in_4bit:
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True
                )
                logger.info("Using 4-bit quantization")
            
            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                padding_side="left"
            )
            
            # Add padding token if not present
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            # Load model with appropriate configuration
            model_kwargs = {
                "device_map": self.device if self.device == "cpu" else "auto",
                "trust_remote_code": True,
                "torch_dtype": torch.float16 if self.device == "cuda" else torch.float32,
                **self.model_kwargs
            }
            
            if quantization_config:
                model_kwargs["quantization_config"] = quantization_config
            
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                **model_kwargs
            )
            
            # Set model to evaluation mode
            self.model.eval()
            
            # Create generation pipeline
            self.generation_pipeline = pipeline(
                "text-generation",
                model=self.model,
                tokenizer=self.tokenizer,
                device_map="auto" if self.device != "cpu" else None,
                device=self.device if self.device == "cpu" else None
            )
            
            logger.info(f"Model loaded successfully. Memory usage: {self._get_memory_usage():.2f} GB")
            
        except Exception as e:
            logger.error(f"Failed to load model {self.model_name}: {e}")
            raise AIConnectionError(f"Model loading failed: {e}")
    
    def _get_memory_usage(self) -> float:
        """
        Get current GPU/CPU memory usage.
        
        Returns:
            Memory usage in GB
        """
        if self.device == "cuda" and torch.cuda.is_available():
            return torch.cuda.memory_allocated() / 1024**3
        return 0.0
    
    def process_text(self, text: str, metadata: Optional[Dict] = None) -> List[Dict]:
        """
        Process document text and generate training samples using the loaded model.
        
        Args:
            text: Extracted text from document
            metadata: Optional document metadata
            
        Returns:
            List of training samples as dictionaries
            
        Raises:
            AIResponseError: If model is not loaded or generation fails
        """
        if self.model is None or self.tokenizer is None:
            raise AIResponseError("Model not loaded. Call _load_model() first.")
        
        # Format the prompt with document content
        prompt = self.format_prompt(text)
        
        # Add document context if metadata provided
        if metadata:
            context_str = "\n\nDocument Information:\n"
            for key, value in metadata.items():
                if value and key not in ['content', 'text', 'full_text']:
                    context_str += f"- {key}: {value}\n"
            prompt = prompt + context_str
        
        try:
            # Generate response using the model
            raw_response = self._generate(prompt)
            
            # Parse JSON from response
            parsed_response = self._parse_json_response(raw_response)
            
            # Ensure response is a list
            if isinstance(parsed_response, dict):
                samples = [parsed_response]
            elif isinstance(parsed_response, list):
                samples = parsed_response
            else:
                raise AIResponseError(f"Unexpected response type: {type(parsed_response)}")
            
            # Validate samples against schema
            valid_samples = []
            for sample in samples:
                if self.validate_response(sample):
                    if metadata:
                        sample['_source_metadata'] = {
                            'filename': metadata.get('filename'),
                            'document_type': metadata.get('mime_type'),
                            'processed_at': datetime.now().isoformat(),
                            'model': self.model_name
                        }
                    valid_samples.append(sample)
                else:
                    logger.warning(f"Invalid sample rejected: {sample}")
            
            if not valid_samples:
                raise AIResponseError("No valid samples generated")
            
            logger.info(f"Generated {len(valid_samples)} valid samples")
            return valid_samples
            
        except torch.cuda.OutOfMemoryError as e:
            logger.error(f"CUDA out of memory: {e}")
            self._free_memory()
            raise AIResponseError(f"Out of memory: {e}") from e
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            raise AIResponseError(f"Generation failed: {e}") from e
        finally:
            # Free memory after processing
            self._free_memory()
    
    def _generate(self, prompt: str) -> str:
        """
        Generate text using the loaded model.
        
        Args:
            prompt: Formatted prompt
            
        Returns:
            Generated text response
        """
        # Prepare generation parameters
        generation_params = {
            "max_new_tokens": self.max_new_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repetition_penalty": self.repetition_penalty,
            "do_sample": self.temperature > 0,
            "pad_token_id": self.tokenizer.pad_token_id,
            "eos_token_id": self.tokenizer.eos_token_id,
        }
        
        # Use pipeline if available, otherwise manual generation
        if self.generation_pipeline:
            result = self.generation_pipeline(
                prompt,
                **generation_params
            )
            generated_text = result[0]['generated_text']
            # Remove the prompt from the response
            if generated_text.startswith(prompt):
                generated_text = generated_text[len(prompt):].strip()
            return generated_text
        else:
            # Manual generation
            inputs = self.tokenizer(prompt, return_tensors="pt")
            
            # Move to device
            if self.device == "cuda":
                inputs = {k: v.to('cuda') for k, v in inputs.items()}
            
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    **generation_params
                )
            
            generated_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            # Remove prompt from response
            if generated_text.startswith(prompt):
                generated_text = generated_text[len(prompt):].strip()
            
            return generated_text
    
    def health_check(self) -> bool:
        """
        Check if the model is loaded and responsive.
        
        Returns:
            True if model is healthy, False otherwise
        """
        try:
            if self.model is None or self.tokenizer is None:
                logger.warning("Model or tokenizer not loaded")
                return False
            
            # Simple test generation
            test_prompt = "Test"
            test_result = self._generate(test_prompt)
            
            return test_result is not None and len(test_result) > 0
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    def get_model_info(self) -> Dict:
        """
        Get information about the loaded model.
        
        Returns:
            Dictionary with model information
        """
        info = {
            "name": self.model_name,
            "backend": "transformers",
            "device": self.device,
            "quantization": None,
            "available": self.model is not None,
            "parameters": "unknown",
            "memory_usage_gb": self._get_memory_usage()
        }
        
        if self.load_in_8bit:
            info["quantization"] = "8-bit"
        elif self.load_in_4bit:
            info["quantization"] = "4-bit"
        
        # Try to get model size if available
        if hasattr(self.model, 'config'):
            if hasattr(self.model.config, 'num_parameters'):
                info["parameters"] = f"{self.model.config.num_parameters / 1e9:.2f}B"
            elif hasattr(self.model.config, 'num_hidden_layers'):
                # Rough estimate
                info["parameters"] = "unknown"
        
        return info
    
    def _free_memory(self):
        """
        Free GPU/CPU memory by clearing caches and collecting garbage.
        
        This is important for long-running processes to prevent memory leaks.
        """
        if self.device == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        
        gc.collect()
        logger.debug(f"Memory freed. Current usage: {self._get_memory_usage():.2f} GB")
    
    def batch_process(self, texts: List[str], 
                     metadata_list: Optional[List[Dict]] = None,
                     batch_size: int = 1) -> List[List[Dict]]:
        """
        Process multiple documents in batches (overridden for memory optimization).
        
        Args:
            texts: List of document texts
            metadata_list: Optional list of metadata dicts
            batch_size: Number of documents to process per batch (recommend 1 for GPU)
            
        Returns:
            List of sample lists, one per input document
        """
        # For transformers, we want to be more conservative with batch sizes
        # to avoid OOM errors. Default to batch_size=1.
        if batch_size > 2 and self.device == "cuda":
            logger.warning(f"Reducing batch size from {batch_size} to 2 for GPU memory safety")
            batch_size = 2
        
        return super().batch_process(texts, metadata_list, batch_size)
    
    def reload_model(self):
        """
        Reload the model (useful after freeing memory or changing configuration).
        """
        logger.info("Reloading model...")
        self._free_memory()
        self.model = None
        self.tokenizer = None
        self.generation_pipeline = None
        self._load_model()
    
    def unload_model(self):
        """
        Completely unload the model to free memory.
        """
        logger.info("Unloading model...")
        self.model = None
        self.tokenizer = None
        self.generation_pipeline = None
        self._free_memory()
        logger.info("Model unloaded")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure model is unloaded."""
        self.unload_model()
    
    def __repr__(self) -> str:
        """String representation."""
        status = "loaded" if self.model else "unloaded"
        return f"TransformersClient(model={self.model_name}, device={self.device}, status={status})"
