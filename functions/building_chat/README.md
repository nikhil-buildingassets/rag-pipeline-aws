# Building Chat - Orchestrated LLM Architecture

A highly scalable, robust, and well-architected LLM-powered chatbot system for building management. This system uses intelligent context classification and resolution to provide accurate, contextual responses based on user queries.

## Architecture Overview

The system follows a modular, orchestrated architecture with the following key components:

### Core Components

1. **ContextClassifier** (`context_classifier.py`)
   - Intelligently determines what type of context is needed for a user query
   - Supports 4 context types: `file_context`, `building_context`, `organization_context`, `general`
   - Uses LLM-based classification with fallback keyword matching
   - Returns confidence scores and reasoning

2. **ContextResolver** (`context_resolver.py`)
   - Fetches and resolves different types of context based on classification
   - Handles file context via vector search (Qdrant)
   - Retrieves building data from RDS database
   - Manages organization-level context
   - Provides fallback mechanisms for error handling

3. **PromptBuilder** (`prompt_builder.py`)
   - Constructs context-specific prompts based on building persona
   - Maintains consistent building personality across all interactions
   - Adds conversation context and history
   - Handles different prompt types for different context scenarios

4. **LLMOrchestrator** (`llm_orchestrator.py`)
   - Coordinates the entire chat flow
   - Manages the orchestration pipeline
   - Handles file processing when needed
   - Generates final responses with metadata
   - Provides comprehensive error handling

### Supporting Components

- **Utils** (`utils.py`) - Shared utilities for database, Qdrant, and OpenAI connections
- **Constants** (`constants.py`) - Configuration constants and environment variables
- **Logger** (`logger.py`) - Centralized logging configuration
- **Load Secrets** (`load_secrets.py`) - AWS Secrets Manager integration

## Context Types

### 1. File Context (`file_context`)
- **Trigger**: Questions about specific files, documents, or uploaded content
- **Keywords**: "this file", "document", "report", "upload", "what's in", "summarize"
- **Action**: Vector search in Qdrant for relevant file chunks
- **Use Case**: Document analysis, file summaries, content extraction

### 2. Building Context (`building_context`)
- **Trigger**: Questions about building-specific data, performance, measures, bills
- **Keywords**: "my building", "energy", "bills", "measures", "performance", "consumption"
- **Action**: Fetch building data from RDS (measures, energy data, bills, building info)
- **Use Case**: Building performance analysis, energy efficiency recommendations

### 3. Organization Context (`organization_context`)
- **Trigger**: Questions about organization-level data, multiple buildings, portfolio
- **Keywords**: "all buildings", "organization", "company", "portfolio", "across buildings"
- **Action**: Fetch organization-wide data and portfolio metrics
- **Use Case**: Portfolio management, cross-building comparisons

### 4. Vector Context (`vector_context`)
- **Trigger**: Questions about historical data, past reports, or information that might be in any document
- **Keywords**: "previous", "historical", "past", "reports", "documents", "analysis", "find", "search"
- **Action**: Semantic search across all documents in vector store for building/org
- **Use Case**: Historical analysis, cross-document insights, comprehensive information retrieval

### 5. General Context (`general`)
- **Trigger**: General questions that don't require specific context
- **Keywords**: "hello", "help", "how to", "what can you do"
- **Action**: Provide general building management guidance
- **Use Case**: System help, general advice, capability explanations

## Flow Diagram

```
User Message
     ↓
Context Classification (LLM + Fallback)
     ↓
File Processing (if needed)
     ↓
Context Resolution (RDS/Qdrant/Vector Store)
     ↓
Prompt Building (Persona + Context)
     ↓
LLM Generation (gpt-4o-mini)
     ↓
Response Formatting + Metadata
     ↓
Return to Frontend
```

## Key Features

### 🚀 Scalability
- Modular architecture allows independent scaling of components
- Efficient context resolution with caching opportunities
- Optimized database queries with proper indexing
- Vector search for fast document retrieval

### 🛡️ Robustness
- Comprehensive error handling at every level
- Fallback mechanisms for classification failures
- Graceful degradation when services are unavailable
- Detailed logging for debugging and monitoring

### 🎯 Intelligence
- LLM-based context classification with confidence scoring
- Building persona maintenance across all interactions
- Conversation history integration
- Multi-modal context resolution (files, building data, organization data)

### 🔧 Maintainability
- Clean separation of concerns
- Well-documented code with type hints
- Consistent error handling patterns
- Modular design for easy testing and updates

## API Endpoint

### Request Format
```json
{
  "message": "What's my building's energy consumption?",
  "buildingId": 123,
  "buildingName": "Downtown Office Tower",
  "organizationId": 456,
  "userEmail": "user@example.com",
  "messageHistory": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi! I'm Downtown Office Tower..."}
  ],
  "fileIds": ["file-uuid-1", "file-uuid-2"],
  "fileUrl": "s3://bucket/path/to/file.pdf"
}
```

### Response Format
```json
{
  "response": "Based on my recent energy data, I've consumed...",
  "metadata": {
    "context_type": "building_context",
    "confidence": 0.95,
    "reason": "User asked about building energy consumption",
    "context_used": true,
    "prompt_confidence": 0.9,
    "model_used": "gpt-4o-mini",
    "tokens_used": 1250,
    "file_ids": [],
    "chunks_used": [],
    "error": null
  }
}
```

## Configuration

### Environment Variables
- `ENVIRONMENT`: Deployment environment (dev/prod)
- `OPENAI_API_KEY`: Stored in AWS Secrets Manager
- Database credentials: Stored in AWS Secrets Manager
- Qdrant credentials: Stored in AWS Secrets Manager

### Dependencies
- `requests`: HTTP client for OpenAI API calls
- `psycopg2`: PostgreSQL database adapter
- `qdrant-client`: Vector database client
- `python-jose`: JWT token handling
- `boto3`: AWS SDK for Lambda and Secrets Manager

## Error Handling

The system implements comprehensive error handling:

1. **Classification Errors**: Fallback to keyword-based classification
2. **Context Resolution Errors**: Graceful degradation with error messages
3. **LLM API Errors**: Retry logic with fallback responses
4. **Database Errors**: Connection retry with proper cleanup
5. **File Processing Errors**: Skip file processing and continue with available context

## Performance Optimizations

1. **Connection Pooling**: Reuse database connections
2. **Vector Search**: Efficient similarity search with proper indexing
3. **Context Caching**: Opportunity for Redis-based caching
4. **Token Management**: Limit message history to prevent token overflow
5. **Parallel Processing**: File processing and context resolution can be parallelized

## Monitoring and Logging

- Structured logging with correlation IDs
- Performance metrics for each component
- Error tracking with stack traces
- Context classification accuracy monitoring
- Token usage tracking for cost optimization

## Cost Tracking and Monitoring

The system includes comprehensive cost tracking for all OpenAI API calls:

### Cost Tracking Features

1. **Real-time Cost Calculation**
   - Tracks costs for embeddings, chat completions, and context classification
   - Uses current OpenAI pricing (configurable)
   - Calculates costs per API call and per session

2. **Detailed Logging**
   - Logs each API call with token usage and cost
   - Session summaries with total costs
   - Request-level cost breakdown

3. **Cost Monitoring**
   - Daily and monthly cost tracking
   - Cost trend analysis
   - Automatic cost alerts for high usage

4. **Response Metadata**
   - Cost information included in response metadata
   - Breakdown by API call type
   - Total session cost

### Cost Alerts

- **High Session Cost**: Alerts when a single request costs >$1.00
- **High Daily Cost**: Alerts when daily costs exceed >$10.00
- **Configurable Thresholds**: Easy to adjust alert levels

### Example Cost Logs

```
OpenAI API Call - Type: classification, Model: gpt-4o-mini, Input Tokens: 150, Output Tokens: 50, Total Tokens: 200, Cost: $0.000030
OpenAI API Call - Type: embedding, Model: text-embedding-3-small, Input Tokens: 100, Output Tokens: 0, Total Tokens: 100, Cost: $0.000002
OpenAI API Call - Type: chat, Model: gpt-4o-mini, Input Tokens: 1200, Output Tokens: 300, Total Tokens: 1500, Cost: $0.000225

=== OpenAI Cost Summary ===
Request ID: 550e8400-e29b-41d4-a716-446655440000
Session Duration: 2.45s
Total API Calls: 3
Total Cost: $0.000257
  classification: 1 calls, 200 tokens, $0.000030
  embedding: 1 calls, 100 tokens, $0.000002
  chat: 1 calls, 1500 tokens, $0.000225
==============================
```

### Response Metadata Example

```json
{
  "response": "Based on your building data...",
  "metadata": {
    "context_type": "building_context",
    "confidence": 0.95,
    "cost_summary": {
      "total_cost_usd": 0.000257,
      "total_api_calls": 3,
      "calls_by_type": {
        "classification": {"count": 1, "total_cost": 0.000030, "total_tokens": 200},
        "embedding": {"count": 1, "total_cost": 0.000002, "total_tokens": 100},
        "chat": {"count": 1, "total_cost": 0.000225, "total_tokens": 1500}
      }
    }
  }
}
```

## Future Enhancements

1. **Caching Layer**: Redis for context and embedding caching
2. **Streaming Responses**: Real-time response generation
3. **Multi-modal Support**: Image and document analysis
4. **Conversation Memory**: Long-term conversation context
5. **A/B Testing**: Different prompt strategies
6. **Analytics Dashboard**: Usage and performance metrics 