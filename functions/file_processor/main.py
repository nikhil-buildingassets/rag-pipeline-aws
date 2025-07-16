import json
import os
import boto3
from pathlib import Path
from typing import Dict, Any, Tuple
import logging

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Set tokenizers parallelism to avoid warnings
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Initialize AWS clients
s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')

LAMBDA_FUNCTIONS = {
    'embed_and_index': 'embed_and_index',
    'measure': 'measures_extraction',
    'equipment': 'equipment_extraction',
    'utility': 'utility_extraction'
}

def get_function_name(alias):
    env = os.environ.get('ENVIRONMENT', 'dev')
    return f"{env}_{LAMBDA_FUNCTIONS[alias]}"

def invoke_function(alias, payload):
    response = lambda_client.invoke(
        FunctionName=get_function_name(alias),
        InvocationType='RequestResponse',
        Payload=json.dumps(payload)
    )
    return response

def get_file_from_s3(bucket: str, key: str) -> Tuple[bytes, str]:
    """Get file content directly from S3 into memory."""
    logger.info(f"Fetching file content from s3://{bucket}/{key}")
    
    try:
        # Get the object from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        # Read the content into memory
        file_content = response['Body'].read()
        filename = Path(key).name
        logger.info(f"Successfully fetched file content, size: {len(file_content)} bytes")
        return file_content, filename
    except Exception as e:
        logger.error(f"Error fetching file from S3: {str(e)}")
        raise

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda handler for orchestrating the RAG pipeline."""
    try:
        # Extract S3 URL from event
        file_url = event.get('file_url')

        if not file_url:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'file_url is required in the event payload'
                })
            }

        # Parse S3 URL
        if not file_url.startswith('s3://'):
            raise ValueError("Invalid S3 URL format. Must start with 's3://'")
        
        # Extract bucket and key from URL
        parts = file_url[5:].split('/', 1)
        if len(parts) != 2:
            raise ValueError("Invalid S3 URL format. Must be 's3://bucket/key'")
        
        bucket, key = parts
        
        # Step 1: Get file content from S3
        logger.info("Step 1: Getting file from S3")
        file_content, filename = get_file_from_s3(bucket, key)
        
        # Step 2: Invoke RAG pipeline to process file and save vectors
        logger.info("Step 2: Invoking RAG pipeline")
        rag_payload = {
            'file_content': file_content.decode('latin1'),  # Convert bytes to string for JSON serialization
            'bucket': bucket,
            'key': key
        }
        rag_result = invoke_function('rag', rag_payload)
        
        if rag_result['status'] != 'success':
            return {
                'statusCode': 500,
                'body': json.dumps(rag_result)
            }

        # TODO: Based on the RAG pipeline result, decide which function to run next
        # This is where you'll add the orchestration logic for subsequent steps
        
        # For now, just return the RAG pipeline result
        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'rag_result': rag_result,
                'next_steps': 'TODO: Add orchestration logic for next steps'
            })
        }
        
    except Exception as e:
        logger.error(f"Error in lambda handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'error',
                'message': str(e)
            })
        }

if __name__ == "__main__":
    # For local testing
    test_event = {
        'file_url': 's3://your-bucket/path/to/document.file'
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))
