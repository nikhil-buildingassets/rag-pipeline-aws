import json
import requests
from typing import Dict, Any, List
from utils import get_openai_api_key
from constants import OPENAI_API_URL
from logger import logger
from cost_tracker import cost_tracker

class ContextClassifier:
    """Determines the type of context needed for a user query."""
    
    def __init__(self):
        self.system_prompt = """
You are an intelligent context classifier for a building management chatbot. Your job is to determine what type of context is needed to best answer the user's question.

Analyze the user's message and return one of these context types:

1. "file_context" - User is asking about specific files, documents, or uploaded content
   - Keywords: "this file", "document", "report", "upload", "what's in", "summarize", "extract"
   - Questions about specific uploaded files or documents

2. "building_context" - User is asking about building-specific data, performance, measures, bills
   - Keywords: "my building", "energy", "bills", "measures", "performance", "consumption", "costs"
   - Questions about building operations, efficiency, maintenance

3. "organization_context" - User is asking about organization-level data, multiple buildings, company-wide info
   - Keywords: "all buildings", "organization", "company", "portfolio", "across buildings"
   - Questions about multiple buildings or organization-wide metrics

4. "vector_context" - User is asking about historical data, past reports, or information that might be in the vector store
   - Keywords: "previous", "historical", "past", "reports", "documents", "analysis", "find", "search"
   - Questions that might benefit from searching through all available documents and reports
   - When user asks for information that could be in any uploaded document or report

5. "general" - General questions that don't require specific context
   - Keywords: "hello", "help", "how to", "what can you do", general advice
   - General questions about the system or capabilities

Return JSON only in this format:
{
    "context_type": "file_context|building_context|organization_context|vector_context|general",
    "confidence": 0.95,
    "reason": "Brief explanation of why this context type was chosen",
    "requires_file_processing": true/false,
    "suggested_actions": ["action1", "action2"]
}

No need to return the reason, confidence, or suggested actions only pure json in the given format.
"""

    def classify(self, message: str, message_history: List[Dict], file_ids: List[str] = None, building_id: int = None) -> Dict[str, Any]:
        """Classify the context type needed for the user's message."""
        try:
            # Prepare the classification prompt
            context_info = f"Available file IDs: {file_ids or []}\nBuilding ID: {building_id or 'None'}"
            
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"Context: {context_info}\n\nUser message: {message}"}
            ]
            
            # Add recent message history for context (last 5 messages)
            if message_history:
                recent_history = message_history[-5:]
                for msg in recent_history:
                    messages.append(msg)
            
            # Prepare request data for cost tracking
            request_data = {
                "model": "gpt-4o-mini",
                "messages": messages,
                "max_tokens": 300,
                "temperature": 0.1
            }
            
            # Make the classification request
            response = requests.post(
                OPENAI_API_URL,
                headers={
                    "Authorization": f"Bearer {get_openai_api_key()}",
                    "Content-Type": "application/json"
                },
                json=request_data,
                timeout=10
            )
            
            if not response.ok:
                logger.error(f"Classification API error: {response.status_code} {response.text}")
                return self._fallback_classification(message)
            
            result = response.json()
            classification_text = result['choices'][0]['message']['content']
            
            # Log cost for classification
            cost_tracker.log_api_call(
                api_type="classification",
                model="gpt-4o-mini",
                usage=result.get('usage', {}),
                request_data=request_data,
                response_data=result
            )
            
            # Parse the JSON response
            try:
                classification = json.loads(classification_text)
                logger.info(f"Context classification: {classification}")
                return classification
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse classification JSON: {e}")
                return self._fallback_classification(message)
                
        except Exception as e:
            logger.error(f"Error in context classification: {str(e)}")
            return self._fallback_classification(message)
    
    def _fallback_classification(self, message: str) -> Dict[str, Any]:
        """Fallback classification when the main classifier fails."""
        message_lower = message.lower()
        
        # Simple keyword-based fallback
        if any(word in message_lower for word in ["file", "document", "upload", "this", "summarize"]):
            return {
                "context_type": "file_context",
                "confidence": 0.7,
                "reason": "Fallback: detected file-related keywords",
                "requires_file_processing": True,
                "suggested_actions": ["process_file", "extract_content"]
            }
        elif any(word in message_lower for word in ["building", "energy", "bills", "measures"]):
            return {
                "context_type": "building_context",
                "confidence": 0.7,
                "reason": "Fallback: detected building-related keywords",
                "requires_file_processing": False,
                "suggested_actions": ["fetch_building_data"]
            }
        elif any(word in message_lower for word in ["organization", "company", "all buildings", "portfolio"]):
            return {
                "context_type": "organization_context",
                "confidence": 0.7,
                "reason": "Fallback: detected organization-related keywords",
                "requires_file_processing": False,
                "suggested_actions": ["fetch_org_data"]
            }
        elif any(word in message_lower for word in ["previous", "historical", "past", "reports", "find", "search", "analysis"]):
            return {
                "context_type": "vector_context",
                "confidence": 0.7,
                "reason": "Fallback: detected vector search keywords",
                "requires_file_processing": False,
                "suggested_actions": ["search_vector_store"]
            }
        else:
            return {
                "context_type": "general",
                "confidence": 0.6,
                "reason": "Fallback: no specific context detected",
                "requires_file_processing": False,
                "suggested_actions": ["general_response"]
            } 