# will tirggers by file_processor.py and gets file file content in bytes
# pass this bytes to process_and_embeds.py and get the vectors
# save this vectors to vector db and return the vector id to file_processor.py

import json
import boto3
import os
from pathlib import Path
from typing import Dict, Any, List
import logging
import pinecone
import numpy as np
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')

# Initialize Pinecone
pinecone.init(
    api_key=os.getenv('PINECONE_API_KEY'),
    environment=os.getenv('PINECONE_ENVIRONMENT', 'us-west1-gcp')
)

PINECONE_INDEX_NAME = f"{os.getenv('ENVIRONMENT')}_{os.getenv('PINECONE_INDEX_NAME')}"

LAMBDA_FUNCTIONS = {
    'embed': 'process_and_embeds',
    'process': 'file_processor',
    'measure': 'measures_extraction',
    'equipment': 'equipment_extraction',
    'utility': 'utility_extraction'
}

def get_function_name(alias):
    env = os.environ.get('ENVIRONMENT', 'dev')
    return f"{env}_{LAMBDA_FUNCTIONS[alias]}"

def invoke_process_and_embed_lambda(file_content: str) -> Dict[str, Any]:
    """Invoke the process_and_embeds Lambda function."""
    try:
        logger.info("Invoking process_and_embeds Lambda")
        response = lambda_client.invoke(
            FunctionName=get_function_name('embed'),
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'file_content': file_content
            })
        )
        
        # Parse the response
        response_payload = json.loads(response['Payload'].read())
        if response['StatusCode'] != 200:
            raise Exception(f"process_and_embeds Lambda failed: {response_payload}")
            
        return json.loads(response_payload['body'])
        
    except Exception as e:
        logger.error(f"Error invoking process_and_embeds Lambda: {str(e)}")
        raise

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda handler for creating vector index and storing in S3."""
    try:
        # Extract parameters from event
        file_content = event.get('file_content')
        bucket = event.get('bucket')
        key = event.get('key')

        if not all([file_content, bucket, key]):
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Missing required parameters in event payload'
                })
            }

        # Step 1: Process file and generate embeddings
        logger.info("Step 1: Processing file and generating embeddings")
        process_result = invoke_process_and_embed_lambda(file_content)
        
        if process_result['status'] != 'success':
            return {
                'statusCode': 500,
                'body': json.dumps(process_result)
            }

        # Step 2: Initialize pipeline and process vectors
        logger.info("Step 2: Creating vector index and saving to Pinecone")
        pipeline = RAGPipeline()
        result = pipeline.process_and_store(bucket, key, process_result)

        return {
            'statusCode': 200 if result['status'] == 'success' else 500,
            'body': json.dumps(result)
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

class RAGPipeline:
    def __init__(self):
        self.index_name = PINECONE_INDEX_NAME
        self._ensure_index_exists()
        self.index = pinecone.Index(self.index_name)
    
    def _ensure_index_exists(self):
        """Ensure the Pinecone index exists, create it if it doesn't."""
        try:
            # Check if index exists
            existing_indexes = pinecone.list_indexes()
            logger.info(f"Existing Pinecone indexes: {existing_indexes}")
            
            if self.index_name not in existing_indexes:
                logger.info(f"Creating Pinecone index: {self.index_name}")
                pinecone.create_index(
                    name=self.index_name,
                    dimension=384,
                    metric='cosine'
                )
                
                # Wait for index to be ready
                logger.info(f"Waiting for index {self.index_name} to be ready...")
                while not pinecone.describe_index(self.index_name).status['ready']:
                    import time
                    time.sleep(1)
                logger.info(f"Index {self.index_name} is ready")
            else:
                logger.info(f"Index {self.index_name} already exists")
                
        except Exception as e:
            logger.error(f"Error ensuring Pinecone index exists: {str(e)}")
            raise

    def _save_chunks_to_s3(self, bucket: str, prefix: str, chunks: List[Dict]) -> str:
        """Save chunks data to S3 and return the S3 path."""
        try:
            # Save chunks
            chunks_path = f"{prefix}/chunks.json"
            chunks_data = json.dumps(chunks, ensure_ascii=False).encode('utf-8')
            s3_client.put_object(Bucket=bucket, Key=chunks_path, Body=chunks_data)
            
            logger.info("Successfully saved chunks to S3")
            return chunks_path
            
        except Exception as e:
            logger.error(f"Error saving chunks to S3: {str(e)}")
            raise

    def process_and_store(self, bucket: str, key: str, process_result: Dict[str, Any]) -> Dict[str, Any]:
        """Store vectors in Pinecone and chunks in S3."""
        try:
            if process_result['status'] != 'success':
                return process_result

            # Extract data from process result
            chunks = process_result['chunks']
            embeddings = process_result['embeddings']
            
            # Prepare vectors for Pinecone
            vectors_to_upsert = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                vector_id = f"{key}_{i}"
                metadata = {
                    'text': chunk['text'],
                    'page': chunk['page'],
                    'word_count': chunk['word_count'],
                    'source': f"s3://{bucket}/{key}",
                    'chunk_index': i
                }
                vectors_to_upsert.append((vector_id, embedding, metadata))
            
            # Upsert to Pinecone
            logger.info(f"Upserting {len(vectors_to_upsert)} vectors to Pinecone")
            self.index.upsert(vectors=vectors_to_upsert)
            
            # Save chunks to S3 for reference
            output_prefix = f"processed/{Path(key).stem}"
            chunks_path = self._save_chunks_to_s3(bucket, output_prefix, chunks)
            
            # Return processing results
            return {
                'status': 'success',
                'file_url': f"s3://{bucket}/{key}",
                'vectors_location': {
                    'pinecone_index': self.index_name,
                    'chunks_path': f"s3://{bucket}/{chunks_path}"
                },
                'stats': process_result['stats'],
                'process_complete': True  # Signal that vector processing is complete
            }
            
        except Exception as e:
            logger.error(f"Error processing and storing vectors: {str(e)}")
            return {
                'status': 'error',
                'error': str(e)
            }
