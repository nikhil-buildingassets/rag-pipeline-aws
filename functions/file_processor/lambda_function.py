import json
import os
import boto3
import base64
from pathlib import Path
from typing import Dict, Any, Tuple
import logging
import psycopg2
from psycopg2.extras import RealDictCursor

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Constants
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')
SECRET_NAME = f'{ENVIRONMENT}-buildingassets-secrets'
FILE_STORAGE_BUCKET_PREFIX = f'{ENVIRONMENT}_buildingassets'

# Initialize AWS clients
s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')
secrets_client = boto3.client('secretsmanager')

LAMBDA_FUNCTIONS = {
    'embed_and_index': 'embed_and_index',
    'measure': 'measures_extraction',
    'equipment': 'equipment_extraction',
    'utility': 'utility_extraction'
}

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

def create_file_tracking(
    file_name: str,
    file_path: str,
    file_type: str,
    building_id: int,
    org_id: int,
    openai_file_id: str | None = None,
    vector_store_id: str | None = None,
    report_type: str | None = None,
    source: str | None = None,
    certificate_id: str | None = None,
) -> dict:
    """Insert a new record into the file_tracking table."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        final_report_type = certificate_id or report_type

        insert_query = """
        INSERT INTO file_tracking (
            file_name,
            file_path,
            file_type,
            vector_id,
            building_id,
            org_id,
            openai_file_id,
            file_status,
            report_type,
            source
        ) VALUES (
            %(file_name)s,
            %(file_path)s,
            %(file_type)s,
            %(vector_id)s,
            %(building_id)s,
            %(org_id)s,
            %(openai_file_id)s,
            %(file_status)s,
            %(report_type)s,
            %(source)s
        )
        RETURNING *;
        """
        file_path = file_path.replace(f'{FILE_STORAGE_BUCKET_PREFIX}/', '')
        cursor.execute(insert_query, {
            'file_name': file_name,
            'file_path': file_path,
            'file_type': file_type,
            'vector_id': vector_store_id,
            'building_id': building_id,
            'org_id': org_id,
            'openai_file_id': openai_file_id,
            'file_status': 'processing',
            'report_type': final_report_type,
            'source': source
        })

        result = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"File tracking record created for {file_name}")
        return result

    except Exception as e:
        logger.error(f"Error inserting file tracking: {str(e)}")
        raise

def get_function_name(alias):
    env = os.environ.get('ENVIRONMENT', 'dev')
    return f"{env}_{LAMBDA_FUNCTIONS[alias]}"

def invoke_function(alias, payload):
    logger.info(f"Invoking function: {alias}, payload: {payload}")
    response = lambda_client.invoke(
        FunctionName=get_function_name(alias),
        InvocationType='RequestResponse',
        Payload=json.dumps(payload)
    )
    
    response_payload = response['Payload'].read()
    logger.info(f"Raw payload from {alias}: {response_payload}")

    # 🔥 Decode the payload JSON
    return json.loads(response_payload)

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
        org_id = event.get('org_id')
        building_id = event.get('building_id')

        file_type = event.get('file_type', '')
        use_admin_folder = event.get('use_admin_folder') == 'true'
        
        # Get report_type if it exists (for measure_report file type)
        report_type = event.get('report_type', None)
        
        # Get source if it exists (which tab/component uploaded the file)
        source = event.get('source', None)
        
        # Check if upload is from measures tab with All Buildings selected
        all_buildings_selected = event.get('all_buildings_selected') == 'true'

        # Get certificate-specific params if applicable
        certificate_id = event.get('certificateId', None)
        report_id = event.get('report_id', None)
        file_path = event.get('file_path', None) # Only used for data_manager source
        upload_id = event.get('upload_id', None)

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
        
        bucket, path = parts
        
        # Step 1: Get file content from S3
        logger.info("Step 1: Getting file from S3")
        file_content, filename = get_file_from_s3(bucket, path)

        # Step 2: Create file_tracking record
        logger.info("Step 2: Creating file_tracking record")
        file_tracking_record = create_file_tracking(
            file_name=filename,
            file_path=path,
            file_type=file_type,
            building_id=building_id,
            org_id=org_id,
            report_type=report_type,
            source=source,
            certificate_id=certificate_id
        )

        file_id = file_tracking_record['id']
        
        # Step 3: Invoke RAG pipeline to process file and save vectors
        logger.info("Step 3: Invoking RAG pipeline")
        embed_and_index_payload = {
            'file_url': file_url,
            'bucket': bucket,
            'path': path,
            'org_id': org_id,
            'building_id': building_id,
            'file_id': file_id
        }
        embed_and_index_result = invoke_function('embed_and_index', embed_and_index_payload)
        
        if embed_and_index_result['status'] != 'success':
            return {
                'statusCode': 500,
                'body': json.dumps(embed_and_index_result)
            }

        # TODO: Based on the RAG pipeline result, decide which function to run next
        # This is where you'll add the orchestration logic for subsequent steps
        
        # For now, just return the RAG pipeline result
        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'rag_result': embed_and_index_result,
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
