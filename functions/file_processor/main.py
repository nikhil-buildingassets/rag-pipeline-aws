# takes file from s3 and process the file with rag_pipeline.py
# accroding to report type create orchestrator function to take
# decision and call the respective function

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

def get_pdf_from_s3(bucket: str, key: str) -> Tuple[bytes, str]:
    """Get PDF content directly from S3 into memory."""
    logger.info(f"Fetching PDF content from s3://{bucket}/{key}")
    
    try:
        # Get the object from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        # Read the content into memory
        pdf_content = response['Body'].read()
        filename = Path(key).name
        logger.info(f"Successfully fetched PDF content, size: {len(pdf_content)} bytes")
        return pdf_content, filename
    except Exception as e:
        logger.error(f"Error fetching PDF from S3: {str(e)}")
        raise

def invoke_rag_pipeline_lambda(pdf_content: bytes, bucket: str, key: str) -> Dict[str, Any]:
    """Invoke the rag_pipeline Lambda function."""
    try:
        logger.info("Invoking rag_pipeline Lambda")
        response = lambda_client.invoke(
            FunctionName='rag_pipeline',
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'pdf_content': pdf_content.decode('latin1'),  # Convert bytes to string for JSON serialization
                'bucket': bucket,
                'key': key
            })
        )
        
        # Parse the response
        response_payload = json.loads(response['Payload'].read())
        if response['StatusCode'] != 200:
            raise Exception(f"rag_pipeline Lambda failed: {response_payload}")
            
        return json.loads(response_payload['body'])
        
    except Exception as e:
        logger.error(f"Error invoking rag_pipeline Lambda: {str(e)}")
        raise

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda handler for orchestrating the RAG pipeline."""
    try:
        # Extract S3 URL from event
        pdf_url = event.get('pdf_url')
        if not pdf_url:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'pdf_url is required in the event payload'
                })
            }

        # Parse S3 URL
        if not pdf_url.startswith('s3://'):
            raise ValueError("Invalid S3 URL format. Must start with 's3://'")
        
        # Extract bucket and key from URL
        parts = pdf_url[5:].split('/', 1)
        if len(parts) != 2:
            raise ValueError("Invalid S3 URL format. Must be 's3://bucket/key'")
        
        bucket, key = parts
        
        # Step 1: Get PDF content from S3
        logger.info("Step 1: Getting PDF from S3")
        pdf_content, filename = get_pdf_from_s3(bucket, key)
        
        # Step 2: Invoke RAG pipeline to process PDF and save vectors
        logger.info("Step 2: Invoking RAG pipeline")
        rag_result = invoke_rag_pipeline_lambda(pdf_content, bucket, key)
        
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
        'pdf_url': 's3://your-bucket/path/to/document.pdf'
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))
