import json
import os
import boto3
from jose import jwt, JWTError
from typing import Dict, Any
from psycopg2.extras import RealDictCursor
from utils import get_db_connection, get_jwt_secret
from constants import *
from logger import logger
from llm_orchestrator import LLMOrchestrator
from cost_tracker import cost_tracker
from cost_monitor import cost_monitor
import uuid

s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')

def verify_jwt(token: str, secret: str):
    """Verify the JWT token using HS256 algorithm."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except JWTError as e:
        print(f"JWT verification error: {e}")
        return None

def validate_request(event):
    """Validate the request by checking the JWT token."""
    auth_header = event['headers'].get('Authorization', '')
    if not auth_header.startswith("Bearer "):
        return None, {
            'statusCode': 401,
            'headers': CORS_HEADERS,
            'body': json.dumps({'message': 'Unauthorized - Missing Bearer token'})
        }

    token = auth_header.split(" ")[1]

    try:
        jwt_secret = get_jwt_secret()
    except Exception as e:
        print(f"Error fetching JWT secret: {e}")
        return None, {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'message': 'Internal server error'})
        }

    payload = verify_jwt(token, jwt_secret)
    if not payload:
        return None, {
            'statusCode': 401,
            'headers': CORS_HEADERS,
            'body': json.dumps({'message': 'Unauthorized - Invalid or expired token'})
        }

    return payload, None

def get_function_name(alias):
    env = os.environ.get('ENVIRONMENT', 'dev')
    return f"{env}_{LAMBDA_FUNCTIONS[alias]}"

def validate_building_access(building_id: int, organization_id: int, user_email: str) -> bool:
    """Validate that the user has access to the building."""
    logger.info(f"Validating access for user {user_email} to building {building_id} in org {organization_id}")
    
    if not user_email:
        logger.error("User email is required for building access validation")
        return False
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Get building information
        cursor.execute(
            """
            SELECT org_id, admin_email, manager_emails
            FROM buildings
            WHERE id = %s
            """,
            (building_id,)
        )
        building = cursor.fetchone()
        if not building:
            logger.error('Building not found')
            return False
        if building['org_id'] != organization_id:
            logger.error(f"Building {building_id} does not belong to organization {organization_id}")
            return False
        # Check if user has access to this organization
        cursor.execute(
            """
            SELECT admin_email
            FROM organizations
            WHERE id = %s
            """,
            (organization_id,)
        )
        org = cursor.fetchone()
        if not org:
            logger.error('Organization not found')
            return False
        # Check if user is org admin or building manager
        is_org_admin = org['admin_email'] == user_email
        manager_emails = building.get('manager_emails', []) if building.get('manager_emails') else []
        is_building_manager = user_email in manager_emails
        has_access = is_org_admin or is_building_manager
        logger.info(f"Access validation result: {has_access} (isOrgAdmin: {is_org_admin}, isBuildingManager: {is_building_manager})")
        return has_access
    except Exception as e:
        logger.error(f"Error validating building access: {str(e)}")
        return False
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def invoke_file_processor_lambda(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke the file_processor Lambda function."""
    try:
        logger.info("Invoking file_processor Lambda")
        response = lambda_client.invoke(
            FunctionName=get_function_name('processor'),
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        
        # Parse the response
        response_payload = json.loads(response['Payload'].read())
        if response['StatusCode'] != 200:
            raise Exception(f"file_processor Lambda failed: {response_payload}")
            
        return json.loads(response_payload['body'])

    except Exception as e:
        logger.error(f"Error invoking file_processor Lambda: {str(e)}")
        raise

def lambda_handler(event, context):
    """Main Lambda handler function using orchestrated LLM architecture."""
    # Generate unique request ID for tracking
    request_id = str(uuid.uuid4())
    
    # Reset cost tracker for new request
    cost_tracker.reset_session()
    
    try:
        logger.info(f"Lambda function invoked with event: {event}")
        logger.info(f"Request ID: {request_id}")
        
        # Handle CORS preflight
        if event.get('httpMethod') == 'OPTIONS':
            return {
                'statusCode': 200,
                'headers': CORS_HEADERS,
                'body': 'OK'
            }
        
        # Parse request body
        body = event.get('body', '{}')
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in request body: {e}")
                return {
                    'statusCode': 400,
                    'headers': CORS_HEADERS,
                    'body': json.dumps({'error': 'Invalid JSON in request body'})
                }
        
        logger.info(f"Parsed request body: {body}")
        
        # Extract parameters
        message = body.get('message')
        building_id = body.get('buildingId')
        building_name = body.get('buildingName')
        organization_id = body.get('organizationId')
        message_history = body.get('messageHistory', [])
        user_email = body.get('userEmail')
        file_ids = body.get('fileIds', [])
        file_url = body.get('fileUrl')
        
        # Validate required parameters
        if not all([message, building_id, building_name, organization_id, user_email]):
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Message, building ID, building name, organization ID, and user email are required'})
            }
        
        # Convert IDs to integers
        building_id = int(building_id)
        organization_id = int(organization_id)
        
        # Validate building access
        if not validate_building_access(building_id, organization_id, user_email):
            return {
                'statusCode': 403,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Access denied'})
            }
        
        # Initialize LLM Orchestrator
        orchestrator = LLMOrchestrator()
        
        # Generate response using orchestrated architecture
        result = orchestrator.generate_response(
            message=message,
            message_history=message_history,
            building_id=building_id,
            organization_id=organization_id,
            building_name=building_name,
            user_email=user_email,
            file_ids=file_ids,
            file_url=file_url
        )
        
        # Log cost summary
        cost_tracker.log_session_summary(request_id)
        
        # Add to cost monitor for tracking over time
        cost_summary = cost_tracker.get_session_summary()
        cost_monitor.add_session_costs(cost_summary, request_id)
        
        # Return response
        if result.get('status') == 'success':
            return {
                'statusCode': 200,
                'headers': CORS_HEADERS,
                'body': json.dumps({
                    'response': result['response'],
                    'metadata': result.get('metadata', {}),
                    'request_id': request_id
                })
            }
        else:
            return {
                'statusCode': 500,
                'headers': CORS_HEADERS,
                'body': json.dumps({
                    'error': result.get('response', 'An error occurred'),
                    'metadata': result.get('metadata', {}),
                    'request_id': request_id
                })
            }
        
    except Exception as e:
        logger.error(f"Error in building_chat: {str(e)}")
        # Log cost summary even on error
        cost_tracker.log_session_summary(request_id)
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': str(e), 'request_id': request_id})
        }
