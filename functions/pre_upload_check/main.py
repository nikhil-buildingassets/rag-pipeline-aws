# Takes file and check file is duplicate or not usiing name and vector similarity
# if duplicate then return the duplicate file if user want to replace then replace the file
# upload file to s3 and run file_processor.py

import json
import os
import boto3
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

# Initialize AWS clients
s3 = boto3.client('s3')
lambda_client = boto3.client('lambda')

def get_file_metadata(bucket, prefix):
    """Get metadata of all files in the bucket with given prefix"""
    files = []
    paginator = s3.get_paginator('list_objects_v2')
    
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        if 'Contents' in page:
            for obj in page['Contents']:
                if obj['Key'].endswith('.txt'):  # Add more file types as needed
                    files.append({
                        'key': obj['Key'],
                        'name': os.path.basename(obj['Key']),
                        'size': obj['Size']
                    })
    return files

def get_file_embedding(bucket, file_key, file_content=None):
    """Get embedding for a file using process_and_embeds Lambda"""
    try:
        # If file_content is provided, first upload it to a temporary location
        temp_key = None
        if file_content:
            temp_key = f"temp/{os.path.basename(file_key)}"
            s3.put_object(
                Bucket=bucket,
                Key=temp_key,
                Body=file_content
            )
            file_key = temp_key

        # Invoke process_and_embeds Lambda synchronously
        response = lambda_client.invoke(
            FunctionName='process_and_embeds',
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'bucket': bucket,
                'file_key': file_key,
                'embedding_only': True  # Flag to indicate we only need the embedding
            })
        )
        
        # Parse response
        payload = json.loads(response['Payload'].read())
        if 'statusCode' in payload and payload['statusCode'] == 200:
            body = json.loads(payload['body'])
            embedding = np.array(body['embedding'])
            
            # Clean up temporary file if it was created
            if temp_key:
                s3.delete_object(Bucket=bucket, Key=temp_key)
                
            return embedding
        else:
            raise Exception(f"Failed to get embedding: {payload}")
            
    except Exception as e:
        if temp_key:
            # Clean up temporary file if it exists
            try:
                s3.delete_object(Bucket=bucket, Key=temp_key)
            except:
                pass
        raise e

def find_similar_files(bucket, file_content, existing_files, similarity_threshold=0.95):
    """Find similar files using vector similarity"""
    if not existing_files:
        return []

    # Get embedding for the new file
    query_embedding = get_file_embedding(bucket, "new_file.txt", file_content)
    
    # Get embeddings for existing files in parallel
    similar_files = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_file = {
            executor.submit(get_file_embedding, bucket, file_meta['key']): file_meta
            for file_meta in existing_files
        }
        
        for future in as_completed(future_to_file):
            file_meta = future_to_file[future]
            try:
                embedding = future.result()
                # Calculate cosine similarity
                similarity = np.dot(query_embedding, embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(embedding)
                )
                
                if similarity > similarity_threshold:
                    similar_files.append({
                        **file_meta,
                        'similarity': float(similarity)
                    })
            except Exception as e:
                print(f"Error processing {file_meta['key']}: {str(e)}")
                continue
    
    return similar_files

def lambda_handler(event, context):
    """
    Lambda handler for pre-upload file check
    
    Expected event structure:
    {
        "bucket": "your-bucket-name",
        "file_key": "path/to/file.txt",
        "file_content": "base64_encoded_content",
        "replace_if_exists": false
    }
    """
    try:
        # Extract parameters
        bucket = event['bucket']
        file_key = event['file_key']
        file_content = event['file_content']
        replace_if_exists = event.get('replace_if_exists', False)
        
        # Get file name and prefix
        file_name = os.path.basename(file_key)
        prefix = os.path.dirname(file_key)
        
        # Get existing files
        existing_files = get_file_metadata(bucket, prefix)
        
        # Check for exact name matches
        name_duplicates = [f for f in existing_files if f['name'] == file_name]
        
        # Check for similar content
        similar_files = find_similar_files(bucket, file_content, existing_files)
        
        if name_duplicates or similar_files:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'isDuplicate': True,
                    'nameMatches': name_duplicates,
                    'similarFiles': similar_files,
                    'message': 'Duplicate or similar files found'
                })
            }
        
        # If no duplicates found or replace_if_exists is True, upload the file
        if not (name_duplicates or similar_files) or replace_if_exists:
            # Upload file to S3
            s3.put_object(
                Bucket=bucket,
                Key=file_key,
                Body=file_content
            )
            
            # Trigger file processor Lambda
            lambda_client.invoke(
                FunctionName='file_processor',
                InvocationType='Event',
                Payload=json.dumps({
                    'bucket': bucket,
                    'file_key': file_key
                })
            )
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'File uploaded successfully',
                    'file_key': file_key
                })
            }
        
        return {
            'statusCode': 400,
            'body': json.dumps({
                'message': 'File not uploaded due to duplicates'
            })
        }
            
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }
