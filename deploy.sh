#!/bin/bash

# Exit on error
set -e

# Default environment and function
ENVIRONMENT="dev"
SPECIFIC_FUNCTION=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --env)
            ENVIRONMENT="$2"
            shift 2
            ;;
        --function)
            SPECIFIC_FUNCTION="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--env dev|prod] [--function function_name]"
            echo "  --env: Environment to deploy to (dev or prod)"
            echo "  --function: Deploy specific function only (optional)"
            exit 1
            ;;
    esac
done

# Validate environment
if [[ "${ENVIRONMENT}" != "dev" && "${ENVIRONMENT}" != "prod" ]]; then
    echo "Invalid environment. Must be either 'dev' or 'prod'"
    exit 1
fi

echo "Deploying to ${ENVIRONMENT} environment"
if [[ -n "${SPECIFIC_FUNCTION}" ]]; then
    echo "Deploying specific function: ${SPECIFIC_FUNCTION}"
fi

# AWS account and region configuration
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=$(aws configure get region)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Function to load environment variables from .env file
load_env_vars() {
    local function_name=$1
    local env_file="functions/${function_name}/.env"
    local env_vars=()
    
    if [[ -f "${env_file}" ]]; then
        echo "Loading environment variables from ${env_file}"
        while IFS='=' read -r key value || [[ -n "$key" ]]; do
            # Skip comments and empty lines
            [[ $key =~ ^#.*$ ]] && continue
            [[ -z "$key" ]] && continue
            
            # Remove any quotes from the value
            value=$(echo "$value" | tr -d '"'"'")
            env_vars+=("${key}=${value}")
        done < "${env_file}"
    else
        echo "Warning: No .env file found for ${function_name}, skipping environment setup."
    fi
    
    echo "${env_vars[@]}"
}

# Function to check if API Gateway exists
check_api_gateway_exists() {
    local api_name=$1
    local api_id=$(aws apigateway get-rest-apis --query "items[?name=='${api_name}'].id" --output text)
    
    if [[ -n "$api_id" && "$api_id" != "None" ]]; then
        echo "$api_id"
        return 0
    else
        return 1
    fi
}

# Function to create API Gateway
create_api_gateway() {
    local api_name=$1
    local lambda_function_name=$2
    
    echo "Creating API Gateway: ${api_name}"
    
    # Create the REST API
    local api_id=$(aws apigateway create-rest-api \
        --name "${api_name}" \
        --description "API for ${lambda_function_name}" \
        --endpoint-configuration types=REGIONAL \
        --query 'id' --output text)
    
    echo "Created API Gateway with ID: ${api_id}"
    
    # Get the root resource ID
    local root_resource_id=$(aws apigateway get-resources \
        --rest-api-id "${api_id}" \
        --query 'items[0].id' --output text)
    
    # Create a proxy resource ({proxy+})
    local proxy_resource_id=$(aws apigateway create-resource \
        --rest-api-id "${api_id}" \
        --parent-id "${root_resource_id}" \
        --path-part "{proxy+}" \
        --query 'id' --output text)
    
    # Create ANY method on the proxy resource
    aws apigateway put-method \
        --rest-api-id "${api_id}" \
        --resource-id "${proxy_resource_id}" \
        --http-method ANY \
        --authorization-type NONE
    
    # Create integration with Lambda
    local lambda_arn="arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:${lambda_function_name}"
    local integration_uri="arn:aws:apigateway:${AWS_REGION}:lambda:path/2015-03-31/functions/${lambda_arn}/invocations"
    
    aws apigateway put-integration \
        --rest-api-id "${api_id}" \
        --resource-id "${proxy_resource_id}" \
        --http-method ANY \
        --type AWS_PROXY \
        --integration-http-method POST \
        --uri "${integration_uri}"
    
    # Create ANY method on the root resource
    aws apigateway put-method \
        --rest-api-id "${api_id}" \
        --resource-id "${root_resource_id}" \
        --http-method ANY \
        --authorization-type NONE
    
    # Create integration with Lambda for root resource
    aws apigateway put-integration \
        --rest-api-id "${api_id}" \
        --resource-id "${root_resource_id}" \
        --http-method ANY \
        --type AWS_PROXY \
        --integration-http-method POST \
        --uri "${integration_uri}"
    
    # Grant API Gateway permission to invoke Lambda
    aws lambda add-permission \
        --function-name "${lambda_function_name}" \
        --statement-id "apigateway-invoke-${api_name}" \
        --action lambda:InvokeFunction \
        --principal apigateway.amazonaws.com \
        --source-arn "arn:aws:execute-api:${AWS_REGION}:${AWS_ACCOUNT_ID}:${api_id}/*/*" \
        --region "${AWS_REGION}" || echo "Permission may already exist"
    
    # Deploy the API
    local deployment_id=$(aws apigateway create-deployment \
        --rest-api-id "${api_id}" \
        --stage-name "${ENVIRONMENT}" \
        --stage-description "Deployment for ${ENVIRONMENT} environment" \
        --query 'id' --output text)
    
    echo "API Gateway deployed with deployment ID: ${deployment_id}"
    echo "API Gateway URL: https://${api_id}.execute-api.${AWS_REGION}.amazonaws.com/${ENVIRONMENT}"
    
    return 0
}

# Function to manage API Gateway for a Lambda function
manage_api_gateway() {
    local function_name=$1
    local prefixed_function_name="${ENVIRONMENT}-${function_name}"
    
    # Convert function name for API Gateway (replace _ with -)
    local api_name="${prefixed_function_name//_/-}"
    
    echo "Managing API Gateway for ${prefixed_function_name}..."
    echo "API Gateway name: ${api_name}"
    
    # Check if API Gateway already exists
    if api_id=$(check_api_gateway_exists "${api_name}"); then
        echo "API Gateway '${api_name}' already exists with ID: ${api_id}"
        echo "Skipping API Gateway creation as it's already attached to Lambda"
    else
        echo "API Gateway '${api_name}' does not exist. Creating..."
        create_api_gateway "${api_name}" "${prefixed_function_name}"
    fi
    
    echo "API Gateway management completed for ${prefixed_function_name}"
    echo "----------------------------------------"
}

# Function to deploy using Docker (ECR)
deploy_with_docker() {
    local function_name=$1
    local function_dir=$2
    local prefixed_function_name=$3
    local image_name=$4
    local image_tag=$5
    
    echo "Deploying ${prefixed_function_name} using Docker..."
    
    # Ensure ECR repository exists
    echo "Checking ECR repository..."
    aws ecr describe-repositories --repository-names "${image_name}" || \
        aws ecr create-repository --repository-name "${image_name}"
    
    # Login to ECR
    echo "Logging into ECR..."
    aws ecr get-login-password --region "${AWS_REGION}" | \
        docker login --username AWS --password-stdin "${ECR_REGISTRY}"
    
    # Build Docker image
    echo "Building Docker image for ${prefixed_function_name}..."
    docker build -t "${image_name}:${image_tag}" \
        --build-arg FUNCTION_DIR="${function_name}" \
        -f "${function_dir}/Dockerfile" .
    
    # Tag and push image to ECR
    echo "Pushing image to ECR..."
    docker tag "${image_name}:${image_tag}" "${ECR_REGISTRY}/${image_name}:${image_tag}"
    docker push "${ECR_REGISTRY}/${image_name}:${image_tag}"
    
    # Update Lambda function code
    echo "Updating Lambda function code with Docker image..."
    aws lambda update-function-code \
        --function-name "${prefixed_function_name}" \
        --image-uri "${ECR_REGISTRY}/${image_name}:${image_tag}"
    
    # Clean up local Docker images
    echo "Cleaning up local images..."
    docker rmi "${image_name}:${image_tag}" "${ECR_REGISTRY}/${image_name}:${image_tag}"
}

# Function to deploy using ZIP file (traditional deployment)
deploy_with_zip() {
    local function_name=$1
    local function_dir=$2
    local prefixed_function_name=$3
    
    echo "Deploying ${prefixed_function_name} using ZIP file..."
    
    # Create temporary directory for packaging
    local temp_dir=$(mktemp -d)
    local zip_file="${temp_dir}/${function_name}.zip"
    
    # Copy function files to temp directory
    echo "Packaging function files..."
    cp -r "${function_dir}"/* "${temp_dir}/"
    
    # Install dependencies if requirements.txt exists
    if [[ -f "${function_dir}/requirements.txt" ]]; then
        echo "Installing Python dependencies..."
        pip install -r "${function_dir}/requirements.txt" -t "${temp_dir}/" --quiet
    fi
    
    # Create ZIP file
    echo "Creating ZIP package..."
    cd "${temp_dir}"
    zip -r "${zip_file}" . -q
    cd - > /dev/null
    
    # Update Lambda function code
    echo "Updating Lambda function code with ZIP file..."
    aws lambda update-function-code \
        --function-name "${prefixed_function_name}" \
        --zip-file "fileb://${zip_file}"
    
    # Clean up temporary files
    echo "Cleaning up temporary files..."
    rm -rf "${temp_dir}"
}

# Function to build and deploy a Lambda function
deploy_function() {
    local function_name=$1
    local function_dir="functions/${function_name}"
    local prefixed_function_name="${ENVIRONMENT}-${function_name}"
    local image_name="${function_name}"
    local image_tag="${ENVIRONMENT}"
    
    # Check if function directory exists and has main.py
    if [[ ! -d "${function_dir}" ]] || [[ ! -f "${function_dir}/main.py" ]]; then
        echo "Skipping ${function_name}: Missing function directory or main.py"
        return
    fi
    
    echo "Deploying ${prefixed_function_name}..."
    echo "----------------------------------------"
    
    # Load environment variables
    local env_vars=($(load_env_vars "${function_name}"))
    
    # Update Lambda function with environment variables
    echo "Updating Lambda function with environment variables..."
    if [ ${#env_vars[@]} -gt 0 ]; then
        # Convert env vars array to JSON format for AWS CLI
        env_json="{"
        for var in "${env_vars[@]}"; do
            key="${var%%=*}"
            value="${var#*=}"
            env_json+="\"${key}\":\"${value}\","
        done
        env_json="${env_json%,}"  # Remove trailing comma
        env_json+="}"
        
        aws lambda update-function-configuration \
            --function-name "${prefixed_function_name}" \
            --environment "Variables=${env_json}"
    fi
    
    # Choose deployment method based on Dockerfile existence
    if [[ -f "${function_dir}/Dockerfile" ]]; then
        echo "Dockerfile found. Using Docker deployment..."
        deploy_with_docker "${function_name}" "${function_dir}" "${prefixed_function_name}" "${image_name}" "${image_tag}"
    else
        echo "No Dockerfile found. Using ZIP deployment..."
        deploy_with_zip "${function_name}" "${function_dir}" "${prefixed_function_name}"
    fi
    
    echo "${prefixed_function_name} deployed successfully"
    echo "----------------------------------------"
    
    # Manage API Gateway for this function
    manage_api_gateway "${function_name}"
}

# Get list of all function directories or validate specific function
if [[ -n "${SPECIFIC_FUNCTION}" ]]; then
    # Deploy specific function
    if [[ -d "functions/${SPECIFIC_FUNCTION}" ]]; then
        echo "Deploying specific function: ${SPECIFIC_FUNCTION}"
        functions=("${SPECIFIC_FUNCTION}")
    else
        echo "Error: Function '${SPECIFIC_FUNCTION}' not found in functions directory"
        exit 1
    fi
else
    # Deploy all functions
    echo "Discovering Lambda functions..."
    functions=()
    for dir in functions/*/; do
        # Remove trailing slash and 'functions/' prefix
        function_name=$(basename "${dir}")
        functions+=("${function_name}")
    done
fi

# Print discovered functions
echo "Found ${#functions[@]} function(s) to deploy:"
printf '%s\n' "${functions[@]}"
echo "----------------------------------------"

# Deploy each function
for function_name in "${functions[@]}"; do
    deploy_function "${function_name}"
done

if [[ -n "${SPECIFIC_FUNCTION}" ]]; then
    echo "Function ${SPECIFIC_FUNCTION} deployed successfully with API Gateway endpoint"
else
    echo "All functions deployed successfully with API Gateway endpoints"
fi
