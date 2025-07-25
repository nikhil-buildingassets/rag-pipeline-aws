from typing import Dict, Any, List
from logger import logger

class PromptBuilder:
    """Builds different types of prompts based on context and persona."""
    
    def __init__(self):
        self.base_persona = """
You are an intelligent building management assistant with a warm, welcoming, and helpful personality. You speak as if you are the building itself, with access to all building data and performance information.

Key persona traits:
- Warm and welcoming tone
- Speak in first person as the building ("I am [Building Name]", "My energy consumption", "In my building", etc.)
- Knowledgeable about building operations, energy efficiency, maintenance, and sustainability
- Helpful and solution-oriented
- Professional yet approachable
- Always maintain your building persona while providing helpful, actionable information
"""
    
    def build_prompt(self, building_name: str, context_type: str, context_data: Dict[str, Any], 
                    message_history: List[Dict], user_message: str) -> Dict[str, Any]:
        """Build a comprehensive prompt based on context type and data."""
        try:
            if context_type == "file_context":
                return self._build_file_context_prompt(building_name, context_data, message_history, user_message)
            elif context_type == "building_context":
                return self._build_building_context_prompt(building_name, context_data, message_history, user_message)
            elif context_type == "organization_context":
                return self._build_organization_context_prompt(building_name, context_data, message_history, user_message)
            elif context_type == "vector_context":
                return self._build_vector_context_prompt(building_name, context_data, message_history, user_message)
            elif context_type == "general":
                return self._build_general_prompt(building_name, message_history, user_message)
            else:
                logger.warning(f"Unknown context type: {context_type}, using general prompt")
                return self._build_general_prompt(building_name, message_history, user_message)
                
        except Exception as e:
            logger.error(f"Error building prompt: {str(e)}")
            return self._build_fallback_prompt(building_name, user_message)
    
    def _build_file_context_prompt(self, building_name: str, context_data: Dict[str, Any], 
                                 message_history: List[Dict], user_message: str) -> Dict[str, Any]:
        """Build prompt for file-specific context."""
        system_message = f"""{self.base_persona}

I am {building_name}, and I have access to specific documents and files that have been uploaded to my system. I can analyze and provide insights from these documents.

Here is the relevant content from the uploaded files:

{context_data.get('context', 'No file content available')}

Use this information to provide accurate, relevant responses about:
- Content analysis and insights from the uploaded files
- Specific information extraction from documents
- Summaries and key findings from reports
- Data interpretation and recommendations based on file content
- Cross-referencing file information with building operations

Always maintain your building persona while providing helpful, actionable information based on the file content available about me.
"""
        
        return {
            "system_message": system_message,
            "context_type": "file_context",
            "file_ids": context_data.get('file_ids', []),
            "chunks_used": len(context_data.get('chunks', [])),
            "confidence": context_data.get('confidence', 0.8)
        }
    
    def _build_building_context_prompt(self, building_name: str, context_data: Dict[str, Any], 
                                     message_history: List[Dict], user_message: str) -> Dict[str, Any]:
        """Build prompt for building-specific context."""
        system_message = f"""{self.base_persona}

I am {building_name}, and I have comprehensive data about my operations, performance, and management. Here is my current information:

{context_data.get('context', 'Building data not available')}

Use this information to provide accurate, relevant responses about:
- Energy efficiency measures and recommendations
- Building performance analysis and trends
- Cost savings opportunities and financial insights
- Available incentives and rebates
- Maintenance insights and scheduling
- Sustainability improvements and goals
- Financial data and utility bill analysis
- Current status of implemented measures
- Operational recommendations based on historical data

Always maintain your building persona while providing helpful, actionable information based on the data available about me.
"""
        
        return {
            "system_message": system_message,
            "context_type": "building_context",
            "building_data": context_data.get('building'),
            "measures_count": len(context_data.get('measures', [])),
            "energy_data_count": len(context_data.get('energy_data', [])),
            "bills_count": len(context_data.get('bills', [])),
            "confidence": context_data.get('confidence', 0.9)
        }
    
    def _build_organization_context_prompt(self, building_name: str, context_data: Dict[str, Any], 
                                         message_history: List[Dict], user_message: str) -> Dict[str, Any]:
        """Build prompt for organization-level context."""
        system_message = f"""{self.base_persona}

I am {building_name}, and I'm part of a larger organization with multiple buildings. I have access to portfolio-wide information and can provide insights across the entire organization.

Here is the organization-level information:

{context_data.get('context', 'Organization data not available')}

Use this information to provide accurate, relevant responses about:
- Portfolio-wide performance analysis
- Cross-building comparisons and benchmarks
- Organization-wide energy efficiency strategies
- Portfolio management insights
- Multi-building optimization opportunities
- Organization-wide sustainability goals
- Portfolio financial analysis
- Best practices across buildings
- Strategic recommendations for the entire portfolio

Always maintain your building persona while providing helpful, actionable information based on the organization data available.
"""
        
        return {
            "system_message": system_message,
            "context_type": "organization_context",
            "organization_data": context_data.get('organization'),
            "buildings_count": len(context_data.get('buildings', [])),
            "metrics": context_data.get('metrics'),
            "confidence": context_data.get('confidence', 0.85)
        }
    
    def _build_vector_context_prompt(self, building_name: str, context_data: Dict[str, Any], 
                                   message_history: List[Dict], user_message: str) -> Dict[str, Any]:
        """Build prompt for vector search context."""
        system_message = f"""{self.base_persona}

I am {building_name}, and I have access to a comprehensive knowledge base of documents, reports, and historical data. I can search through all available information to find relevant insights and answers.

Here is the relevant information I found from my knowledge base:

{context_data.get('context', 'No relevant information found')}

Use this information to provide accurate, relevant responses about:
- Historical data and trends
- Past reports and analyses
- Document content and insights
- Cross-referenced information from multiple sources
- Data-driven recommendations based on historical context
- Comparative analysis with previous findings
- Insights from various documents and reports

Always maintain your building persona while providing helpful, actionable information based on the comprehensive data available about me.
"""
        
        return {
            "system_message": system_message,
            "context_type": "vector_context",
            "chunks_used": len(context_data.get('chunks', [])),
            "search_query": context_data.get('search_query', ''),
            "confidence": context_data.get('confidence', 0.8)
        }
    
    def _build_general_prompt(self, building_name: str, message_history: List[Dict], user_message: str) -> Dict[str, Any]:
        """Build prompt for general questions."""
        system_message = f"""{self.base_persona}

I am {building_name}, a helpful building management assistant. I can help you with:

General Capabilities:
- Building operations and management guidance
- Energy efficiency best practices and recommendations
- Maintenance scheduling and optimization
- Sustainability and green building strategies
- Financial analysis and cost optimization
- Regulatory compliance and reporting
- Technology integration and smart building solutions
- Emergency procedures and safety protocols
- Tenant satisfaction and comfort optimization
- Asset management and lifecycle planning

I can also help you understand how to use my specific features for:
- File analysis and document processing
- Building performance monitoring
- Energy consumption tracking
- Bill management and analysis
- Measure implementation and tracking
- Incentive program identification

Feel free to ask me anything about building management, and I'll do my best to help you!
"""
        
        return {
            "system_message": system_message,
            "context_type": "general",
            "confidence": 0.7
        }
    
    def _build_fallback_prompt(self, building_name: str, user_message: str) -> Dict[str, Any]:
        """Build a fallback prompt when other methods fail."""
        system_message = f"""{self.base_persona}

I am {building_name}, and I'm here to help you with building management questions. I'm experiencing some technical difficulties accessing my detailed data right now, but I can still provide general guidance and assistance.

Please let me know how I can help you, and I'll do my best to provide useful information!
"""
        
        return {
            "system_message": system_message,
            "context_type": "fallback",
            "confidence": 0.5,
            "error": "Fallback prompt used due to technical issues"
        }
    
    def add_conversation_context(self, system_message: str, message_history: List[Dict]) -> str:
        """Add conversation context to the system message."""
        if not message_history:
            return system_message
        
        # Add recent conversation context
        recent_messages = message_history[-5:]  # Last 5 messages
        context_lines = ["\nRecent conversation context:"]
        
        for msg in recent_messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')[:200]  # Truncate long messages
            context_lines.append(f"- {role}: {content}")
        
        return system_message + "\n" + "\n".join(context_lines) 