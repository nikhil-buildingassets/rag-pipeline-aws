import json
import os
import base64
import boto3
import numpy as np
import logging

# Initialize AWS clients
s3 = boto3.client('s3')
lambda_client = boto3.client('lambda')

LAMBDA_FUNCTIONS = {
    'embed': 'process_and_embeds',
    'processor': 'file_processor'
}

def get_function_name(alias):
    env = os.environ.get('ENVIRONMENT', 'dev')
    return f"{env}_{LAMBDA_FUNCTIONS[alias]}"

def ensure_folder_structure(bucket, file_key):
    """
    Ensures all folders in the path exist by creating empty objects with trailing slashes
    
    Args:
        bucket (str): S3 bucket name
        file_key (str): Full path of the file in S3 (e.g., 'org_folder/BuildingA/measures/report.pdf')
    """
    # Split the path into components
    path_parts = file_key.split('/')
    
    # Don't process the last part as it's the file name
    folder_path = path_parts[:-1]
    
    # Build folders incrementally
    current_path = ""
    for folder in folder_path:
        current_path += folder + "/"
        try:
            # Check if folder exists
            s3.head_object(Bucket=bucket, Key=current_path)
        except:
            # Create folder if it doesn't exist
            try:
                s3.put_object(Bucket=bucket, Key=current_path, Body="")
                logging.info(f"Created folder: {current_path}")
            except Exception as e:
                raise Exception(f"Failed to create folder {current_path}: {str(e)}")

def get_file_metadata(bucket, prefix):
    """Get metadata of all files in the bucket with given prefix"""
    files = []
    paginator = s3.get_paginator('list_objects_v2')
    
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        if 'Contents' in page:
            for obj in page['Contents']:
                files.append({
                    'key': obj['Key'],
                    'name': os.path.basename(obj['Key']),
                    'size': obj['Size']
                })
    return files

def get_file_embedding(file_content):
    """Get embedding for file content using process_and_embeds Lambda"""
    try:
        # Invoke process_and_embeds Lambda synchronously
        response = lambda_client.invoke(
            FunctionName=get_function_name('embed'),
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'content': base64.b64encode(file_content).decode('utf-8'),
                'embedding_only': True
            })
        )
        
        # Parse response
        payload = json.loads(response['Payload'].read())
        if 'statusCode' in payload and payload['statusCode'] == 200:
            body = json.loads(payload['body'])
            if body.get('status') == 'success' and 'embedding' in body:
                embedding = np.array(body['embedding'])
                return embedding
            else:
                raise Exception(f"Invalid embedding response: {body}")
        else:
            raise Exception(f"Failed to get embedding: {payload}")
            
    except Exception as e:
        raise Exception(f"Error getting embedding: {str(e)}")

def get_existing_file_embeddings(bucket, existing_files):
    """Get embeddings for existing files"""
    embeddings = {}
    
    for file_meta in existing_files:
        try:
            # Get file content from S3
            response = s3.get_object(Bucket=bucket, Key=file_meta['key'])
            file_content = response['Body'].read()
            
            # Get embedding
            embedding = get_file_embedding(file_content)
            embeddings[file_meta['key']] = {
                'meta': file_meta,
                'embedding': embedding
            }
        except Exception as e:
            logging.error(f"Error processing {file_meta['key']}: {str(e)}")
            continue
    
    return embeddings

def find_similar_files(file_content, existing_files_data, similarity_threshold=0.95):
    """Find similar files using vector similarity"""
    if not existing_files_data:
        return []

    # Get embedding for the new file
    try:
        query_embedding = get_file_embedding(file_content)
    except Exception as e:
        raise Exception(f"Error getting query embedding: {str(e)}")
    
    similar_files = []
    for file_key, data in existing_files_data.items():
        try:
            # Calculate cosine similarity
            similarity = np.dot(query_embedding, data['embedding']) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(data['embedding'])
            )
            
            if similarity > similarity_threshold:
                similar_files.append({
                    **data['meta'],
                    'similarity': float(similarity)
                })
        except Exception as e:
            logging.error(f"Error calculating similarity for {file_key}: {str(e)}")
            continue
    
    return similar_files

def lambda_handler(event, context):
    """
    Lambda handler for pre-upload file check
    
    Expected event structure:
    {
        "bucket": "your-bucket-name",
        "file_key": "path/to/file",
        "file_content": "base64_encoded_content",
        "replace_if_exists": false,
        "org_folder": "organization_folder_name"  # Added this field
    }
    """
    try:
        # Extract parameters
        bucket = event['bucket']
        file_key = event['file_key']
        file_content_base64 = event['file_content']
        replace_if_exists = event.get('replace_if_exists', False)
        org_folder = event.get('org_folder')
        
        # If org_folder is provided, prepend it to the file_key
        if org_folder:
            file_key = f"{org_folder}/{file_key}"
        
        # Decode base64 file content
        try:
            file_content = base64.b64decode(file_content_base64)
        except Exception as e:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Invalid file content encoding',
                    'details': str(e)
                })
            }
        
        # Get file name and prefix
        file_name = os.path.basename(file_key)
        prefix = os.path.dirname(file_key)
        
        # Get existing files
        existing_files = get_file_metadata(bucket, prefix)
        
        # Check for exact name matches
        name_duplicates = [f for f in existing_files if f['name'] == file_name]
        
        # If name duplicate found and not replacing, return early
        if name_duplicates and not replace_if_exists:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'isDuplicate': True,
                    'nameMatches': name_duplicates,
                    'message': 'File with same name already exists'
                })
            }
        
        # Get embeddings for existing files
        existing_files_data = get_existing_file_embeddings(bucket, existing_files)
        
        # Check for similar content
        similar_files = find_similar_files(file_content, existing_files_data)
        
        if similar_files and not replace_if_exists:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'isDuplicate': True,
                    'similarFiles': similar_files,
                    'message': 'Similar content already exists'
                })
            }
        
        # If no duplicates found or replace_if_exists is True, ensure folder structure exists and upload the file
        try:
            # Create folder structure if it doesn't exist
            ensure_folder_structure(bucket, file_key)
            
            # Upload file to S3
            s3.put_object(
                Bucket=bucket,
                Key=file_key,
                Body=file_content
            )
            
            # Trigger file processor asynchronously
            try:
                lambda_client.invoke(
                    FunctionName=get_function_name('processor'),
                    InvocationType='Event',  # Async invocation
                    Payload=json.dumps({
                        'file_url': f's3://{bucket}/{file_key}'
                    })
                )
            except Exception as e:
                logging.warning(f"Failed to trigger file processor: {str(e)}")
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'File uploaded successfully',
                    'file_key': file_key
                })
            }
        except Exception as e:
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': 'Failed to upload file',
                    'details': str(e)
                })
            }
            
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }
