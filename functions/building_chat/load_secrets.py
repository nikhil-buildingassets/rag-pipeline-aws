import json
import boto3
from constants import *
from logger import logger

secrets_client = boto3.client('secretsmanager')

def load_secrets():
    """Load secrets from Secrets Manager."""
    try:
        secret_response = secrets_client.get_secret_value(
            SecretId=SECRET_NAME
        )
        return json.loads(secret_response['SecretString'])
    except Exception as e:
        logger.error(f"Error loading secrets: {str(e)}")
        raise
