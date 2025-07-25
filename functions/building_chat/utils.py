from qdrant_client import QdrantClient
from requests.auth import HTTPBasicAuth
from logger import logger
from load_secrets import load_secrets
import psycopg2

def get_jwt_secret():
    """Fetch the JWT secret from Secrets Manager."""
    credentials = load_secrets()
    if not credentials:
        raise Exception("Failed to load secrets")
    
    if not credentials['JWT_SECRET']:
        raise Exception("JWT secret not found in secrets")
    
    return credentials['JWT_SECRET']

def get_qdrant_client():
    """Get Qdrant client using credentials from Secrets Manager."""
    try:
        credentials = load_secrets()
        if not credentials:
            raise Exception("Failed to load secrets")
        
        if not credentials['QDRANT_URL'] or not credentials['QDRANT_API_KEY'] or not credentials['QDRANT_USER'] or not credentials['QDRANT_PASSWORD']:
            raise Exception("Missing Qdrant credentials")
        
        q_client = QdrantClient(
            url=credentials['QDRANT_URL'], 
            port=80, 
            api_key=credentials['QDRANT_API_KEY'],
            auth=HTTPBasicAuth(credentials['QDRANT_USER'], credentials['QDRANT_PASSWORD'])
        )
        return q_client
    except Exception as e:
        logger.error(f"Error getting Qdrant client: {str(e)}")
        raise


def get_db_connection():
    """Get database connection using credentials from Secrets Manager."""
    try:
        credentials = load_secrets()
        if not credentials:
            raise Exception("Failed to load secrets")
        
        if not credentials['DB_HOST'] or not credentials['DB_NAME'] or not credentials['DB_ADMIN_USER'] or not credentials['DB_ADMIN_PASSWORD']:
            raise Exception("Missing database credentials")
        
        conn = psycopg2.connect(
            host=credentials['DB_HOST'],
            database=credentials['DB_NAME'],
            user=credentials['DB_ADMIN_USER'],
            password=credentials['DB_ADMIN_PASSWORD']
        )
        return conn
    except Exception as e:
        logger.error(f"Error getting database connection: {str(e)}")
        raise


def get_openai_api_key():
    """Fetch the OpenAI API key from Secrets Manager."""
    credentials = load_secrets()
    if not credentials:
        raise Exception("Failed to load secrets")
    
    if not credentials['OPENAI_API_KEY']:
        raise Exception("OpenAI API key not found in secrets")
    
    return credentials['OPENAI_API_KEY']
