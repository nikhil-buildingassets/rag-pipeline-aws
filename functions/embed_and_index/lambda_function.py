import json
import boto3
import os
from pathlib import Path
from typing import Dict, Any, List
import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import psycopg2
from psycopg2.extras import execute_batch, Json
from uuid import uuid4
from requests.auth import HTTPBasicAuth

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Constants
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')
SECRET_NAME = f'{ENVIRONMENT}-buildingassets-secrets'
COLLECTION_NAME = "BuildingAssets"

LAMBDA_FUNCTIONS = {
    'embed': 'process_and_embeds',
    'process': 'file_processor',
    'measure': 'measures_extraction',
    'equipment': 'equipment_extraction',
    'utility': 'utility_extraction'
}

# Initialize AWS clients
s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')
secrets_client = boto3.client('secretsmanager')

def get_qdrant_client():
    """Get Qdrant client using credentials from Secrets Manager."""
    try:
        secret_response = secrets_client.get_secret_value(
            SecretId=SECRET_NAME
        )
        credentials = json.loads(secret_response['SecretString'])
        
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

q_client = get_qdrant_client()

def get_db_connection():
    """Get database connection using credentials from Secrets Manager."""
    try:
        secret_response = secrets_client.get_secret_value(
            SecretId=SECRET_NAME
        )
        credentials = json.loads(secret_response['SecretString'])
        
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

def create_file_chunk_vector(file_id: str, vectors_to_upsert: List[PointStruct]):
    """
    Save chunk vectors and metadata to RDS.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        insert_query = """
        INSERT INTO file_chunk_vector (
            file_id,
            qdrant_id,
            embedding,
            chunk_index,
            page_number,
            word_count,
            chunk_size,
            overlap,
            text,
            payload
        ) VALUES (
            %(file_id)s,
            %(qdrant_id)s,
            %(embedding)s,
            %(chunk_index)s,
            %(page_number)s,
            %(word_count)s,
            %(chunk_size)s,
            %(overlap)s,
            %(text)s,
            %(payload)s
        )
        """

        insert_data = []
        for point in vectors_to_upsert:
            payload = point.payload
            insert_data.append({
                "file_id": file_id,
                "qdrant_id": point.id,
                "embedding": list(point.vector),  # Convert numpy array to list
                "chunk_index": payload.get("chunk_index"),
                "page_number": payload.get("page"),
                "word_count": payload.get("word_count"),
                "chunk_size": payload.get("chunk_size", 512),  # default if not set
                "overlap": payload.get("overlap", 50),
                "text": payload.get("text"),
                "payload": Json(payload)
            })

        execute_batch(cursor, insert_query, insert_data, page_size=100)
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Inserted {len(insert_data)} chunk vectors into file_chunk_vector")

    except Exception as e:
        logger.error(f"Error inserting chunk vectors into RDS: {str(e)}")
        raise

def get_function_name(alias):
    env = os.environ.get('ENVIRONMENT', 'dev')
    return f"{env}_{LAMBDA_FUNCTIONS[alias]}"

def invoke_process_and_embed_lambda(file_url: str) -> Dict[str, Any]:
    """Invoke the process_and_embeds Lambda function."""
    try:
        logger.info("Invoking process_and_embeds Lambda")
        response = lambda_client.invoke(
            FunctionName=get_function_name('embed'),
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'file_url': file_url
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
        file_url = event.get('file_url')
        bucket = event.get('bucket')
        org_id = event.get('org_id')
        building_id = event.get('building_id')
        file_id = event.get('file_id')
        path = event.get('path')

        logger.info(f"Event: {event}")

        if not all([org_id, building_id, file_id, file_url, bucket, path]):
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Missing required parameters in event payload'
                })
            }

        # Step 1: Process file and generate embeddings
        logger.info("Step 1: Processing file and generating embeddings")
        process_result = invoke_process_and_embed_lambda(file_url)
        
        if process_result['status'] != 'success':
            return {
                'statusCode': 500,
                'body': json.dumps(process_result)
            }

        # Step 2: Initialize pipeline and process vectors
        logger.info("Step 2: Creating vector index and saving to Qdrant")
        pipeline = RAGPipeline()
        result = pipeline.process_and_store(bucket, path, org_id, building_id, file_id, process_result)

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
        self.collection_name = COLLECTION_NAME
        self._ensure_collection_exists()

    def _ensure_collection_exists(self):
        """Ensure the Qdrant collection exists, create it if it doesn't."""
        try:
            # Check if collection exists
            if not q_client.collection_exists(self.collection_name):
                q_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
                )

            else:
                logger.info(f"Collection {self.collection_name} already exists")

        except Exception as e:
            logger.error(f"Error ensuring Qdrant collection exists: {str(e)}")
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

    def process_and_store(self, bucket: str, path: str, org_id: int, building_id: int, file_id: str, process_result: Dict[str, Any]) -> Dict[str, Any]:
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
                vector_id = str(uuid4())
                
                payload = {
                    'org_id': org_id,
                    'building_id': building_id,
                    'file_id': file_id,
                    'text': chunk['text'],
                    'page': chunk['page'],
                    'custom_id': f"vs_{org_id}_{building_id}_{file_id}_{i}",
                    'word_count': chunk['word_count'],
                    'source': f"s3://{bucket}/{path}",
                    'chunk_index': i
                }
                vectors_to_upsert.append(PointStruct(id=vector_id, vector=embedding, payload=payload))
            
            # Upsert to Qdrant
            logger.info(f"Upserting {len(vectors_to_upsert)} vectors to Qdrant")
            operation_info = q_client.upsert(collection_name=self.collection_name, wait=False, points=vectors_to_upsert)

            create_file_chunk_vector(file_id, vectors_to_upsert)
            
            # Save chunks to S3 for reference
            parent_prefix = str(Path(path).parent)
            file_stem = Path(path).stem
            output_prefix = f"{parent_prefix}/processed/{file_stem}"
            chunks_path = self._save_chunks_to_s3(bucket, output_prefix, chunks)
            
            return {
                'status': 'success',
                'file_url': f"s3://{bucket}/{path}",
                'vectors_location': {
                    'qdrant_collection': self.collection_name,
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
