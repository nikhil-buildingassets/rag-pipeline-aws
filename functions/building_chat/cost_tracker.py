import json
import time
from typing import Dict, Any, List
from logger import logger

class OpenAICostTracker:
    """Tracks costs for all OpenAI API calls."""
    
    PRICING = {
        'gpt-4o-mini': {
            'input': 0.00040,   # $0.40 per 1M input tokens
            'output': 0.00160    # $1.60 per 1M output tokens
        },
        'text-embedding-3-small': {
            'input': 0.00002    # $0.02 per 1M input tokens
        }
    }
    
    def __init__(self):
        self.total_cost = 0.0
        self.api_calls = []
        self.session_start_time = time.time()
    
    def log_api_call(self, api_type: str, model: str, usage: Dict[str, Any], 
                    request_data: Dict[str, Any] = None, response_data: Dict[str, Any] = None):
        """Log an OpenAI API call with cost calculation."""
        try:
            # Calculate cost
            cost = self._calculate_cost(model, usage)
            
            # Create call record
            call_record = {
                'timestamp': time.time(),
                'api_type': api_type,  # 'chat', 'embedding', 'classification'
                'model': model,
                'usage': usage,
                'cost_usd': cost,
                'request_data': request_data,
                'response_data': response_data
            }
            
            # Add to tracking
            self.api_calls.append(call_record)
            self.total_cost += cost
            
            # Log the call
            logger.info(f"OpenAI API Call - Type: {api_type}, Model: {model}, "
                       f"Input Tokens: {usage.get('prompt_tokens', 0)}, "
                       f"Output Tokens: {usage.get('completion_tokens', 0)}, "
                       f"Total Tokens: {usage.get('total_tokens', 0)}, "
                       f"Cost: ${cost:.6f}")
            
            return cost
            
        except Exception as e:
            logger.error(f"Error logging API call: {str(e)}")
            return 0.0
    
    def _calculate_cost(self, model: str, usage: Dict[str, Any]) -> float:
        """Calculate cost for a specific model and usage."""
        if model not in self.PRICING:
            logger.warning(f"Unknown model pricing for: {model}")
            return 0.0
        
        pricing = self.PRICING[model]
        cost = 0.0
        
        # Calculate input token cost
        if 'prompt_tokens' in usage and 'input' in pricing:
            input_cost = (usage['prompt_tokens'] / 1_000_000) * pricing['input']
            cost += input_cost
        
        # Calculate output token cost
        if 'completion_tokens' in usage and 'output' in pricing:
            output_cost = (usage['completion_tokens'] / 1_000_000) * pricing['output']
            cost += output_cost
        
        return cost
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of all API calls in this session."""
        session_duration = time.time() - self.session_start_time
        
        # Group by API type
        calls_by_type = {}
        for call in self.api_calls:
            api_type = call['api_type']
            if api_type not in calls_by_type:
                calls_by_type[api_type] = {
                    'count': 0,
                    'total_cost': 0.0,
                    'total_tokens': 0
                }
            
            calls_by_type[api_type]['count'] += 1
            calls_by_type[api_type]['total_cost'] += call['cost_usd']
            calls_by_type[api_type]['total_tokens'] += call['usage'].get('total_tokens', 0)
        
        return {
            'session_duration_seconds': session_duration,
            'total_api_calls': len(self.api_calls),
            'total_cost_usd': self.total_cost,
            'calls_by_type': calls_by_type,
            'api_calls': self.api_calls
        }
    
    def log_session_summary(self, request_id: str = None):
        """Log the complete session summary."""
        summary = self.get_session_summary()
        
        logger.info(f"=== OpenAI Cost Summary ===")
        if request_id:
            logger.info(f"Request ID: {request_id}")
        logger.info(f"Session Duration: {summary['session_duration_seconds']:.2f}s")
        logger.info(f"Total API Calls: {summary['total_api_calls']}")
        logger.info(f"Total Cost: ${summary['total_cost_usd']:.6f}")
        
        for api_type, stats in summary['calls_by_type'].items():
            logger.info(f"  {api_type}: {stats['count']} calls, "
                       f"{stats['total_tokens']} tokens, ${stats['total_cost']:.6f}")
        
        logger.info("=" * 30)
    
    def reset_session(self):
        """Reset the session for a new request."""
        self.total_cost = 0.0
        self.api_calls = []
        self.session_start_time = time.time()

# Global cost tracker instance
cost_tracker = OpenAICostTracker() 