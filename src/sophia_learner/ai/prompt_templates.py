"""
Prompt Templates - Manage and render prompts for AI training data generation

This module provides a flexible template system for creating prompts
that guide AI models to generate training data from documents.
Supports both simple string formatting and Jinja2 templates.
"""

import re
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

from ..utils.logger import get_logger

logger = get_logger(__name__)

# Try to import Jinja2 for advanced templating
try:
    from jinja2 import Template, Environment, meta, exceptions as jinja2_exceptions
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False
    logger.debug("Jinja2 not available, falling back to string formatting")


class PromptTemplate:
    """
    Manage and render prompt templates for AI model interaction.
    
    This class handles loading templates from files or using built-in defaults,
    rendering them with document content and context variables, and validating
    template syntax.
    
    Features:
        - Load templates from file paths
        - Built-in default template for instruction-output generation
        - Support for Jinja2 (if installed) or simple string formatting
        - Template validation
        - Context variable injection
    
    Attributes:
        template: The template string
        template_path: Path to template file (if loaded from file)
        use_jinja2: Whether to use Jinja2 for rendering
    """
    
    # Built-in template types
    DEFAULT = "default"
    QA_PAIR = "qa_pair"
    SUMMARY = "summary"
    CLASSIFICATION = "classification"
    CONVERSATION = "conversation"
    
    def __init__(self, template_path: Optional[Path] = None, template_type: str = "default"):
        """
        Initialize the prompt template.
        
        Args:
            template_path: Optional path to a template file
            template_type: Type of built-in template to use if no path provided
                          (default, qa_pair, summary, classification, conversation)
        """
        self.template_path = template_path
        self.template_type = template_type
        self.template = None
        self.use_jinja2 = JINJA2_AVAILABLE
        
        # Load the template
        if template_path:
            self._load_from_file(template_path)
        else:
            self.template = self._get_builtin_template(template_type)
        
        # Validate the template
        if not self.validate_template(self.template):
            logger.warning(f"Template validation failed for {template_path or template_type}")
        
        logger.debug(f"PromptTemplate initialized: type={template_type}, "
                    f"jinja2={self.use_jinja2}, path={template_path}")
    
    def _load_from_file(self, template_path: Path):
        """
        Load template from a file.
        
        Args:
            template_path: Path to template file
            
        Raises:
            FileNotFoundError: If template file doesn't exist
            IOError: If file cannot be read
        """
        resolved_path = Path(template_path).resolve()
        
        if not resolved_path.exists():
            raise FileNotFoundError(f"Template file not found: {resolved_path}")
        
        try:
            self.template = resolved_path.read_text(encoding='utf-8')
            logger.info(f"Loaded template from {resolved_path} ({len(self.template)} chars)")
        except Exception as e:
            logger.error(f"Failed to load template from {resolved_path}: {e}")
            raise IOError(f"Cannot read template file: {e}")
    
    def _get_builtin_template(self, template_type: str) -> str:
        """
        Get a built-in template by type.
        
        Args:
            template_type: Type of template to retrieve
            
        Returns:
            Template string
            
        Raises:
            ValueError: If template_type is unknown
        """
        templates = {
            self.DEFAULT: self.get_default_template(),
            self.QA_PAIR: self._get_qa_pair_template(),
            self.SUMMARY: self._get_summary_template(),
            self.CLASSIFICATION: self._get_classification_template(),
            self.CONVERSATION: self._get_conversation_template()
        }
        
        if template_type not in templates:
            raise ValueError(f"Unknown template type: {template_type}. "
                           f"Available: {list(templates.keys())}")
        
        return templates[template_type]
    
    def render(self, content: str, context: Optional[Dict] = None) -> str:
        """
        Render the template with document content and context variables.
        
        Args:
            content: Document content to insert into template
            context: Additional context variables (e.g., metadata, instructions)
            
        Returns:
            Rendered prompt string
        """
        if not self.template:
            raise ValueError("No template loaded")
        
        # Prepare the full context
        render_context = {
            'content': content,
            'content_length': len(content),
            'word_count': len(content.split()),
            'line_count': content.count('\n') + 1,
            'timestamp': datetime.now().isoformat(),
            'date': datetime.now().strftime("%Y-%m-%d"),
            'time': datetime.now().strftime("%H:%M:%S"),
        }
        
        # Merge user-provided context
        if context:
            render_context.update(context)
        
        # Render using Jinja2 or string formatting
        if self.use_jinja2 and JINJA2_AVAILABLE:
            return self._render_jinja2(render_context)
        else:
            return self._render_format(render_context)
    
    def _render_jinja2(self, context: Dict) -> str:
        """
        Render template using Jinja2.
        
        Args:
            context: Dictionary of variables for template
            
        Returns:
            Rendered string
        """
        try:
            jinja_template = Template(self.template)
            rendered = jinja_template.render(**context)
            return rendered
        except jinja2_exceptions.TemplateError as e:
            logger.error(f"Jinja2 rendering error: {e}")
            # Fall back to string formatting
            logger.warning("Falling back to string formatting")
            return self._render_format(context)
    
    def _render_format(self, context: Dict) -> str:
        """
        Render template using Python string formatting.
        
        Supports both {variable} and {variable:format} syntax.
        
        Args:
            context: Dictionary of variables for template
            
        Returns:
            Rendered string
        """
        try:
            # Try to format with all context variables
            return self.template.format(**context)
        except KeyError as e:
            # Missing key - try to provide a default
            missing_key = str(e).strip("'")
            logger.warning(f"Missing context variable in template: {missing_key}")
            
            # Create a context with empty string for missing keys and retry
            safe_context = {k: context.get(k, '') for k in self._get_template_variables()}
            return self.template.format(**safe_context)
        except Exception as e:
            logger.error(f"String formatting error: {e}")
            # Last resort: simple replacement
            result = self.template
            for key, value in context.items():
                result = result.replace(f'{{{key}}}', str(value))
            return result
    
    def _get_template_variables(self) -> set:
        """
        Extract variable names from the template.
        
        Returns:
            Set of variable names used in the template
        """
        if self.use_jinja2 and JINJA2_AVAILABLE:
            # Jinja2 variable extraction
            try:
                env = Environment()
                ast = env.parse(self.template)
                return meta.find_undeclared_variables(ast)
            except Exception:
                pass
        
        # Simple regex for {variable} patterns
        pattern = r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}'
        variables = set(re.findall(pattern, self.template))
        return variables
    
    def validate_template(self, template: Optional[str] = None) -> bool:
        """
        Validate the template syntax.
        
        Checks for:
            - Basic syntax errors
            - Missing closing braces
            - Unmatched Jinja2 tags (if using Jinja2)
        
        Args:
            template: Optional template string (uses self.template if None)
            
        Returns:
            True if template is valid, False otherwise
        """
        template_to_check = template or self.template
        
        if not template_to_check:
            logger.warning("Empty template")
            return False
        
        # Check for unclosed braces
        brace_count = template_to_check.count('{') - template_to_check.count('}')
        if brace_count != 0:
            logger.warning(f"Template has {abs(brace_count)} unclosed braces")
            return False
        
        # Check for unclosed brackets
        bracket_count = template_to_check.count('[') - template_to_check.count(']')
        if bracket_count != 0:
            logger.warning(f"Template has {abs(bracket_count)} unclosed brackets")
            return False
        
        # Jinja2-specific validation
        if self.use_jinja2 and JINJA2_AVAILABLE:
            try:
                Environment().parse(template_to_check)
            except jinja2_exceptions.TemplateSyntaxError as e:
                logger.warning(f"Jinja2 syntax error: {e}")
                return False
        
        return True
    
    def get_default_template(self) -> str:
        """
        Get the default prompt template for generating training data.
        
        This template instructs the AI to generate instruction-output pairs,
        question-answer pairs, and other training samples from document content.
        
        Returns:
            Default template string
        """
        return """You are an expert AI training data generator. Your task is to create high-quality training samples from the provided document.

## Document Content:
{content}

## Instructions:
1. Read the document carefully and understand its key points
2. Generate diverse training samples including:
   - Question-answer pairs that test comprehension
   - Instruction-output pairs for tasks described in the document
   - Key facts and statements for knowledge distillation
   - Summaries of main sections

3. For each sample, provide:
   - **type**: One of: "qa", "instruction", "fact", "summary"
   - **input**: The question, instruction, or prompt
   - **output**: The expected response or answer
   - **difficulty**: "easy", "medium", or "hard"
   - **topic**: Main topic area (max 3 words)

4. Generate 3-5 samples that would be valuable for fine-tuning a language model

## Output Format:
Return a JSON array of objects. Example:
[
  {{
    "type": "qa",
    "input": "What is the main purpose of this document?",
    "output": "The main purpose is to...",
    "difficulty": "easy",
    "topic": "overview"
  }},
  {{
    "type": "instruction",
    "input": "Explain how to implement the described process",
    "output": "Step-by-step instructions...",
    "difficulty": "medium",
    "topic": "implementation"
  }}
]

Generate the training samples now:"""
    
    def _get_qa_pair_template(self) -> str:
        """Get a template focused on generating QA pairs."""
        return """You are creating question-answer pairs for AI training.

## Document:
{content}

## Task:
Generate {num_questions|default(5)} high-quality question-answer pairs based on this document.

## Requirements:
- Questions should test different levels of understanding (from basic facts to analysis)
- Answers should be accurate, complete, and based solely on the document
- Include a mix of question types: factual, explanatory, comparative, and applied
- Mark difficulty level for each

## Output Format (JSON array):
[
  {{
    "type": "qa",
    "input": "question text",
    "output": "answer text",
    "difficulty": "easy|medium|hard",
    "topic": "topic name"
  }}
]

Generate QA pairs now:"""
    
    def _get_summary_template(self) -> str:
        """Get a template focused on generating summaries."""
        return """You are creating document summaries for AI training.

## Document:
{content}

## Task:
Generate {num_summaries|default(3)} summaries at different detail levels.

## Summary Levels:
1. **One-sentence summary**: Most concise, captures main idea
2. **Short summary**: 2-3 sentences, key points only  
3. **Detailed summary**: 1 paragraph, comprehensive overview

## Output Format (JSON array):
[
  {{
    "type": "summary",
    "input": "Summarize the document at {level} level",
    "output": "summary text",
    "difficulty": "medium",
    "topic": "main topic"
  }}
]

Generate summaries now:"""
    
    def _get_classification_template(self) -> str:
        """Get a template focused on label/classification extraction."""
        return """You are extracting categories and labels from documents for AI training.

## Document:
{content}

## Task:
Identify and extract classification labels from this document.

## Categories to identify:
- Domain/Subject Area
- Document Type (report, guide, policy, tutorial, etc.)
- Target Audience
- Key Concepts/Terms (max 5)
- Sentiment/Tone
- Action Required (yes/no)

## Output Format (JSON array):
[
  {{
    "type": "classification",
    "input": "What is the {category} of this document?",
    "output": "classification value",
    "difficulty": "easy",
    "topic": "classification"
  }}
]

Extract classifications now:"""
    
    def _get_conversation_template(self) -> str:
        """Get a template for generating conversational training data."""
        return """You are generating conversational training data from document content.

## Document:
{content}

## Task:
Create {num_conversations|default(2)} realistic conversations about this document.

## Conversation Types:
1. **Expert explaining to beginner**: The expert answers questions about the topic
2. **Peer discussion**: Two knowledgeable people discussing implications
3. **Q&A session**: One person asking questions, another providing answers

## Output Format (JSON array):
[
  {{
    "type": "conversation",
    "input": "Conversation topic or starting prompt",
    "output": "Full conversation with speaker labels (e.g., 'A: ...\\nB: ...')",
    "difficulty": "hard",
    "topic": "conversation topic"
  }}
]

Generate conversations now:"""
    
    def get_template_variables(self) -> set:
        """
        Get all variables expected by the template.
        
        Returns:
            Set of variable names
        """
        return self._get_template_variables()
    
    def set_template(self, template: str):
        """
        Set a new template string.
        
        Args:
            template: New template string
        """
        self.template = template
        if not self.validate_template():
            logger.warning("New template failed validation")
    
    def save_to_file(self, file_path: Path):
        """
        Save the current template to a file.
        
        Args:
            file_path: Path where to save the template
        """
        if not self.template:
            raise ValueError("No template to save")
        
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(self.template, encoding='utf-8')
        logger.info(f"Template saved to {file_path}")
    
    def __repr__(self) -> str:
        """String representation."""
        source = self.template_path or self.template_type
        return f"PromptTemplate(source={source}, jinja2={self.use_jinja2}, length={len(self.template) if self.template else 0})"


# Convenience functions for common use cases

def load_template(template_path: Path, template_type: str = "default") -> PromptTemplate:
    """
    Load a prompt template from a file.
    
    Args:
        template_path: Path to template file
        template_type: Fallback type if loading fails
        
    Returns:
        PromptTemplate instance
    """
    try:
        return PromptTemplate(template_path=template_path)
    except Exception as e:
        logger.warning(f"Failed to load template from {template_path}: {e}")
        logger.info(f"Using built-in template: {template_type}")
        return PromptTemplate(template_type=template_type)


def create_custom_template(instructions: str, examples: Optional[str] = None) -> str:
    """
    Create a custom template from instructions and examples.
    
    Args:
        instructions: Custom instructions for the AI
        examples: Optional example outputs
        
    Returns:
        Custom template string
    """
    template = f"""## Instructions:
{instructions}

## Document Content:
{{content}}

## Task:
Generate training samples following these instructions.
"""
    
    if examples:
        template += f"""
## Examples:
{examples}
"""
    
    template += """
## Output Format:
Return a JSON array of training samples.

Generate samples now:"""
    
    return template


def get_available_template_types() -> list:
    """
    Get list of available built-in template types.
    
    Returns:
        List of template type names
    """
    return [
        PromptTemplate.DEFAULT,
        PromptTemplate.QA_PAIR,
        PromptTemplate.SUMMARY,
        PromptTemplate.CLASSIFICATION,
        PromptTemplate.CONVERSATION
    ]
