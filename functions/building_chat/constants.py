import os

ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
OPENAI_API_URL = 'https://api.openai.com/v1/chat/completions'
SECRET_NAME = f'{ENVIRONMENT}-buildingassets-secrets'
OPENAI_EMBEDDING_URL = 'https://api.openai.com/v1/embeddings'

if ENVIRONMENT == 'dev':
    COLLECTION_NAME = 'dev-buildingassets'
elif ENVIRONMENT == 'prod':
    COLLECTION_NAME = 'buildingassets'

if ENVIRONMENT == 'dev':
    BUCKET_NAME = 'dev-buildingassets'
elif ENVIRONMENT == 'prod':
    BUCKET_NAME = 'buildingassets'

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type, cache-control',
    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
    'Access-Control-Expose-Headers': '*',
    'Content-Type': 'application/json'
}

LAMBDA_FUNCTIONS = {
    'processor': 'file_processor'
}