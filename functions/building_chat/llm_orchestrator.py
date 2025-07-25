import requests
from typing import Dict, Any, List
from context_classifier import ContextClassifier
from context_resolver import ContextResolver
from prompt_builder import PromptBuilder
from utils import get_openai_api_key
from constants import OPENAI_API_URL
from logger import logger
from cost_tracker import cost_tracker

class LLMOrchestrator:
    """Orchestrates the entire LLM chat flow with context classification and resolution."""
    
    def __init__(self):
        self.classifier = ContextClassifier()
        self.resolver = ContextResolver()
        self.prompt_builder = PromptBuilder()
    
    def generate_response(self, message: str, message_history: List[Dict], 
                         building_id: int, organization_id: int, building_name: str,
                         user_email: str, file_ids: List[str] = None, 
                         file_url: str = None) -> Dict[str, Any]:
        """Generate a comprehensive response using the orchestrated architecture."""
        try:
            logger.info(f"Starting LLM orchestration for building {building_id}")
            
            # Step 1: Classify the context type needed
            classification = self._classify_context(message, message_history, file_ids, building_id)
            logger.info(f"Context classification: {classification['context_type']}")
            
            # Step 2: Process file if needed
            processed_file_ids = self._process_file_if_needed(
                classification, file_url, building_id, organization_id, file_ids
            )
            
            # Step 3: Resolve context based on classification
            context_data = self._resolve_context(
                classification['context_type'], message, processed_file_ids, 
                building_id, organization_id, user_email
            )
            
            # Step 4: Build the prompt
            prompt_data = self._build_prompt(
                building_name, classification['context_type'], context_data, 
                message_history, message
            )
            
            # Step 5: Generate LLM response
            llm_response = self._generate_llm_response(prompt_data, message_history, message)
            
            # Step 6: Format and return response
            return self._format_response(
                llm_response, classification, context_data, prompt_data
            )
            
        except Exception as e:
            logger.error(f"Error in LLM orchestration: {str(e)}")
            return self._generate_error_response(str(e))
    
    def _classify_context(self, message: str, message_history: List[Dict], 
                         file_ids: List[str], building_id: int) -> Dict[str, Any]:
        """Classify the context type needed for the message."""
        try:
            return self.classifier.classify(message, message_history, file_ids, building_id)
        except Exception as e:
            logger.error(f"Error in context classification: {str(e)}")
            return {
                "context_type": "general",
                "confidence": 0.5,
                "reason": "Fallback due to classification error",
                "requires_file_processing": False,
                "suggested_actions": ["general_response"]
            }
    
    def _process_file_if_needed(self, classification: Dict[str, Any], file_url: str,
                               building_id: int, organization_id: int, 
                               existing_file_ids: List[str]) -> List[str]:
        """Process file if needed based on classification."""
        try:
            if not classification.get('requires_file_processing', False) or not file_url:
                return existing_file_ids or []
            
            # Extract file path from S3 URL
            if file_url.startswith('s3://'):
                parts = file_url[5:].split('/', 1)
                if len(parts) != 2:
                    logger.error("Invalid S3 URL format")
                    return existing_file_ids or []
                
                file_path = parts[1]
                
                # Prepare payload for file processor
                payload = {
                    'org_id': organization_id,
                    'building_id': building_id,
                    'file_type': '',
                    'use_admin_folder': 'false',
                    'report_type': None,
                    'source': 'chat',
                    'all_buildings_selected': 'false',
                    'certificateId': None,
                    'report_id': None,
                    'upload_id': None,
                    'file_path': file_path,
                    'file_url': file_url,
                    'wait_for_vectors': False
                }
                
                # Invoke file processor
                from lambda_function import invoke_file_processor_lambda
                result = invoke_file_processor_lambda(payload)
                
                if result.get('status') == 'success':
                    file_id = result.get('file_id')
                    if file_id:
                        return [file_id] + (existing_file_ids or [])
                    else:
                        logger.warning("File processor succeeded but no file_id returned")
                        return existing_file_ids or []
                else:
                    logger.error(f"File processor failed: {result}")
                    return existing_file_ids or []
            else:
                logger.warning(f"Unsupported file URL format: {file_url}")
                return existing_file_ids or []
                
        except Exception as e:
            logger.error(f"Error processing file: {str(e)}")
            return existing_file_ids or []
    
    def _resolve_context(self, context_type: str, message: str, file_ids: List[str],
                        building_id: int, organization_id: int, user_email: str) -> Dict[str, Any]:
        """Resolve context based on the classification type."""
        try:
            return self.resolver.resolve_context(
                context_type, message, file_ids, building_id, organization_id, user_email
            )
        except Exception as e:
            logger.error(f"Error resolving context: {str(e)}")
            return {
                "context": "Unable to load specific context due to technical issues.",
                "error": str(e),
                "context_type": context_type
            }
    
    def _build_prompt(self, building_name: str, context_type: str, context_data: Dict[str, Any],
                     message_history: List[Dict], user_message: str) -> Dict[str, Any]:
        """Build the prompt based on context type and data."""
        try:
            prompt_data = self.prompt_builder.build_prompt(
                building_name, context_type, context_data, message_history, user_message
            )
            
            # Add conversation context
            if message_history:
                prompt_data['system_message'] = self.prompt_builder.add_conversation_context(
                    prompt_data['system_message'], message_history
                )
            
            return prompt_data
            
        except Exception as e:
            logger.error(f"Error building prompt: {str(e)}")
            return {
                "system_message": f"You are {building_name}, a helpful building management assistant. I'm experiencing technical difficulties but will do my best to help you.",
                "context_type": "fallback",
                "confidence": 0.5
            }
    
    def _generate_llm_response(self, prompt_data: Dict[str, Any], 
                             message_history: List[Dict], user_message: str) -> Dict[str, Any]:
        """Generate response from the LLM."""
        try:
            # Prepare messages for OpenAI
            messages = [
                {"role": "system", "content": prompt_data['system_message']}
            ]
            
            # Add message history (limit to last 10 messages to avoid token limits)
            if message_history:
                recent_history = message_history[-10:]
                messages.extend(recent_history)
            
            # Add current user message
            messages.append({"role": "user", "content": user_message})
            
            # Prepare request data for cost tracking
            request_data = {
                "model": "gpt-4o-mini",
                "messages": messages,
                "max_tokens": 1000,
                "temperature": 0.7
            }
            
            # Make request to OpenAI
            response = requests.post(
                OPENAI_API_URL,
                headers={
                    "Authorization": f"Bearer {get_openai_api_key()}",
                    "Content-Type": "application/json"
                },
                json=request_data,
                timeout=30
            )
            
            if not response.ok:
                raise Exception(f"OpenAI API error: {response.status_code} {response.text}")
            
            result = response.json()
            
            # Log cost for chat completion
            cost_tracker.log_api_call(
                api_type="chat",
                model="gpt-4o-mini",
                usage=result.get('usage', {}),
                request_data=request_data,
                response_data=result
            )
            
            if not result.get('choices') or len(result['choices']) == 0:
                raise Exception("No response from OpenAI")
            
            assistant_message = result['choices'][0]['message']['content']
            
            return {
                "response": assistant_message,
                "usage": result.get('usage', {}),
                "model": result.get('model', 'gpt-4o-mini')
            }
            
        except Exception as e:
            logger.error(f"Error generating LLM response: {str(e)}")
            raise
    
    def _format_response(self, llm_response: Dict[str, Any], classification: Dict[str, Any],
                        context_data: Dict[str, Any], prompt_data: Dict[str, Any]) -> Dict[str, Any]:
        """Format the final response with metadata."""
        try:
            # Get cost summary
            cost_summary = cost_tracker.get_session_summary()
            
            return {
                "response": llm_response['response'],
                "metadata": {
                    "context_type": classification['context_type'],
                    "confidence": classification.get('confidence', 0.0),
                    "reason": classification.get('reason', ''),
                    "context_used": bool(context_data.get('context')),
                    "prompt_confidence": prompt_data.get('confidence', 0.0),
                    "model_used": llm_response.get('model', 'gpt-4o-mini'),
                    "tokens_used": llm_response.get('usage', {}).get('total_tokens', 0),
                    "file_ids": context_data.get('file_ids', []),
                    "chunks_used": context_data.get('chunks', []),
                    "error": context_data.get('error'),
                    "cost_summary": {
                        "total_cost_usd": cost_summary['total_cost_usd'],
                        "total_api_calls": cost_summary['total_api_calls'],
                        "calls_by_type": cost_summary['calls_by_type']
                    }
                },
                "status": "success"
            }
            
        except Exception as e:
            logger.error(f"Error formatting response: {str(e)}")
            return {
                "response": "I apologize, but I encountered an issue processing your request. Please try again.",
                "metadata": {
                    "context_type": "fallback",
                    "confidence": 0.0,
                    "error": str(e)
                },
                "status": "error"
            }
    
    def _generate_error_response(self, error_message: str) -> Dict[str, Any]:
        """Generate an error response when orchestration fails."""
        return {
            "response": "I apologize, but I'm experiencing technical difficulties right now. Please try again in a moment.",
            "metadata": {
                "context_type": "error",
                "confidence": 0.0,
                "error": error_message
            },
            "status": "error"
        }
