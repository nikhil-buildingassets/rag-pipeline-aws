# will tirggers by file_processor.py and gets pdf file content in bytes
# pass this bytes to process_and_embeds.py and get the vectors
# save this vectors to vector db and return the vector id to file_processor.py

import json
import boto3
import io
from pathlib import Path
from typing import Dict, Any, List
import logging
import faiss
import numpy as np

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')

def invoke_process_and_embed_lambda(pdf_content: str) -> Dict[str, Any]:
    """Invoke the process_and_embeds Lambda function."""
    try:
        logger.info("Invoking process_and_embeds Lambda")
        response = lambda_client.invoke(
            FunctionName='process_and_embeds',
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'pdf_content': pdf_content
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
        pdf_content = event.get('pdf_content')
        bucket = event.get('bucket')
        key = event.get('key')

        if not all([pdf_content, bucket, key]):
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Missing required parameters in event payload'
                })
            }

        # Step 1: Process PDF and generate embeddings
        logger.info("Step 1: Processing PDF and generating embeddings")
        process_result = invoke_process_and_embed_lambda(pdf_content)
        
        if process_result['status'] != 'success':
            return {
                'statusCode': 500,
                'body': json.dumps(process_result)
            }

        # Step 2: Initialize pipeline and process vectors
        logger.info("Step 2: Creating vector index and saving to S3")
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
        pass

    def create_vector_index(self, embeddings: List[List[float]]) -> faiss.Index:
        """Create optimized FAISS index from embeddings."""
        try:
            # Convert embeddings list back to numpy array
            embeddings_array = np.array(embeddings)
            
            # Create and populate the index
            dimension = embeddings_array.shape[1]
            index = faiss.IndexFlatIP(dimension)  # Using Inner Product for normalized vectors
            index.add(embeddings_array)
            
            logger.info("Created FAISS index")
            return index
            
        except Exception as e:
            logger.error(f"Error creating vector index: {str(e)}")
            raise

    def _save_vectors_to_s3(self, bucket: str, prefix: str, chunks: List[Dict], 
                           embeddings: List[List[float]], index: faiss.Index) -> Dict[str, str]:
        """Save vectorizer data directly to S3 and return the S3 paths."""
        s3_paths = {}
        
        try:
            # Save embeddings
            s3_paths['embeddings'] = f"{prefix}/embeddings.npy"
            embeddings_array = np.array(embeddings)
            with io.BytesIO() as buffer:
                np.save(buffer, embeddings_array)
                buffer.seek(0)
                s3_client.put_object(Bucket=bucket, Key=s3_paths['embeddings'], Body=buffer.read())
            
            # Save chunks
            s3_paths['chunks'] = f"{prefix}/chunks.json"
            chunks_data = json.dumps(chunks, ensure_ascii=False).encode('utf-8')
            s3_client.put_object(Bucket=bucket, Key=s3_paths['chunks'], Body=chunks_data)
            
            # Save FAISS index
            s3_paths['index'] = f"{prefix}/index.faiss"
            with io.BytesIO() as buffer:
                faiss.write_index(index, buffer)
                buffer.seek(0)
                s3_client.put_object(Bucket=bucket, Key=s3_paths['index'], Body=buffer.read())
            
            logger.info("Successfully saved vectors to S3")
            return s3_paths
            
        except Exception as e:
            logger.error(f"Error saving vectors to S3: {str(e)}")
            raise

    def process_and_store(self, bucket: str, key: str, process_result: Dict[str, Any]) -> Dict[str, Any]:
        """Create vector index and save to S3."""
        try:
            if process_result['status'] != 'success':
                return process_result

            # Extract data from process result
            chunks = process_result['chunks']
            embeddings = process_result['embeddings']
            
            # Create vector index
            logger.info("Creating vector index...")
            index = self.create_vector_index(embeddings)
            
            # Save vectors to S3
            output_prefix = f"processed/{Path(key).stem}"
            s3_paths = self._save_vectors_to_s3(bucket, output_prefix, chunks, embeddings, index)
            
            # Return processing results
            return {
                'status': 'success',
                'pdf_url': f"s3://{bucket}/{key}",
                'vectors_location': {
                    'bucket': bucket,
                    'paths': s3_paths
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
