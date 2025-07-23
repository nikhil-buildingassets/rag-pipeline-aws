#!/bin/bash

# Exit on error
set -e

# Default environment and function
ENVIRONMENT="dev"
SPECIFIC_FUNCTION=""

# AWS account and region configuration
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=$(aws configure get region)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# API and project configuration
API_NAME="buildingassets-api"
PROJECT_NAME="Building Assets"

# Function to cleanup temporary files
cleanup() {
    if [[ -f ".api_gateway_id" ]]; then
        rm -f .api_gateway_id
    fi
}

# Set trap to cleanup on exit
trap cleanup EXIT

# Check if jq is available
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed. Please install jq to continue."
    echo "On macOS: brew install jq"
    echo "On Ubuntu/Debian: sudo apt-get install jq"
    echo "On CentOS/RHEL: sudo yum install jq"
    exit 1
fi

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

# Function to load environment variables from .env file
load_env_vars() {
    local function_name=$1
    local env_file="functions/${function_name}/.env"
    local vars=""
    local first=true

    if [[ -f "${env_file}" ]]; then
        while IFS='=' read -r key value || [[ -n "$key" ]]; do
            # Skip comments and empty lines
            [[ $key =~ ^[[:space:]]*# ]] && continue
            [[ -z "$key" ]] && continue

            # Trim whitespace
            key=$(echo "$key" | xargs)
            value=$(echo "$value" | xargs)

            # Remove any quotes
            value=$(echo "$value" | tr -d '"')

            # Add to key=value string
            if [ "$first" = true ]; then
                first=false
            else
                vars+=","
            fi
            vars+="${key}=${value}"
        done < "${env_file}"
    fi

    echo "{${vars}}"
}

# Function to check if shared HTTP API exists
check_shared_http_api_exists() {
    local api_name="${API_NAME}"
    local api_id=$(aws apigatewayv2 get-apis --query "Items[?Name=='${api_name}'].ApiId" --output text)
    
    if [[ -n "$api_id" && "$api_id" != "None" ]]; then
        # Validate that the HTTP API is accessible
        if aws apigatewayv2 get-api --api-id "${api_id}" >/dev/null 2>&1; then
            echo "$api_id"
            return 0
        else
            echo "Found broken HTTP API ${api_id}, will recreate..." >&2
            # Delete the broken HTTP API
            aws apigatewayv2 delete-api --api-id "${api_id}" 2>/dev/null || true
            return 1
        fi
    else
        return 1
    fi
}

# Function to create shared HTTP API
create_shared_http_api() {
    local api_name="${API_NAME}"
    
    echo "Creating shared HTTP API: ${api_name}"
    
    # Create the HTTP API
    local api_id=$(aws apigatewayv2 create-api \
        --name "${api_name}" \
        --description "Shared HTTP API for ${PROJECT_NAME} to manage the Lambda functions endpoints" \
        --protocol-type HTTP \
        --cors-configuration '{
            "AllowMethods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "AllowOrigins": ["*"],
            "AllowHeaders": ["*"],
            "MaxAge": 86400
        }' \
        --query 'ApiId' --output text)
    
    echo "Created shared HTTP API with ID: ${api_id}"
    
    # Store API ID for later use
    echo "${api_id}" > .api_gateway_id
    
    echo "Shared HTTP API created successfully"
    echo "HTTP API URL: https://${api_id}.execute-api.${AWS_REGION}.amazonaws.com"
    
    return 0
}

# Function to get or create shared HTTP API
get_or_create_shared_http_api() {
    local api_id
    
    # Always check for existing HTTP API first
    if api_id=$(check_shared_http_api_exists); then
        echo "Shared HTTP API already exists with ID: ${api_id}" >&2
        echo "${api_id}" > .api_gateway_id
    else
        echo "Shared HTTP API does not exist. Creating..." >&2
        create_shared_http_api
        # Read the API ID from the file that was just created
        if [[ -f ".api_gateway_id" ]]; then
            api_id=$(cat .api_gateway_id)
        else
            echo "Error: Failed to create HTTP API or retrieve API ID" >&2
            return 1
        fi
    fi
    
    echo "${api_id}"
}

# Function to add function route to shared HTTP API
add_function_route() {
    local function_name=$1
    local prefixed_function_name=$2
    local api_id=$3
    
    echo "Adding route for function: ${function_name}"
    
    # Wait a moment for resources to be available
    sleep 5
    
    # Create route path for the function
    local route_path="/${function_name}"
    
    # Check if integration already exists by looking for any integration with this Lambda
    local integration_id
    local integration_exists=$(aws apigatewayv2 get-integrations --api-id "${api_id}" --query "Items[?IntegrationUri=='arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:${prefixed_function_name}'].IntegrationId" --output text)
    
    if [[ -z "${integration_exists}" || "${integration_exists}" == "None" ]]; then
        echo "Creating Lambda integration for ${prefixed_function_name}"
        
        # Create the integration
        integration_id=$(aws apigatewayv2 create-integration \
            --api-id "${api_id}" \
            --integration-type AWS_PROXY \
            --integration-uri "arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:${prefixed_function_name}" \
            --payload-format-version "2.0" \
            --query 'IntegrationId' --output text)
        
        if [[ -z "${integration_id}" || "${integration_id}" == "None" ]]; then
            echo "❌ Failed to create integration"
            return 1
        fi
        
        echo "✅ Created integration ID: ${integration_id}"
    else
        echo "✅ Lambda integration already exists: ${integration_exists}"
        integration_id="${integration_exists}"
    fi
    
    # Check if route already exists
    local route_exists=$(aws apigatewayv2 get-routes --api-id "${api_id}" --query "Items[?RouteKey=='ANY ${route_path}'].RouteId" --output text)
    
    if [[ -z "${route_exists}" || "${route_exists}" == "None" ]]; then
        echo "Creating route: ANY ${route_path}"
        
        # Create the route using the actual integration ID
        local route_id=$(aws apigatewayv2 create-route \
            --api-id "${api_id}" \
            --route-key "ANY ${route_path}" \
            --target "integrations/${integration_id}" \
            --query 'RouteId' --output text)
        
        if [[ -z "${route_id}" || "${route_id}" == "None" ]]; then
            echo "❌ Failed to create route"
            return 1
        fi
        
        echo "✅ Created route ID: ${route_id}"
    else
        echo "✅ Route already exists: ${route_exists}"
    fi
    
    # Grant HTTP API permission to invoke Lambda
    echo "Granting Lambda permission..."
    aws lambda add-permission \
        --function-name "${prefixed_function_name}" \
        --statement-id "apigatewayv2-invoke-${function_name}-${ENVIRONMENT}" \
        --action lambda:InvokeFunction \
        --principal apigateway.amazonaws.com \
        --source-arn "arn:aws:execute-api:${AWS_REGION}:${AWS_ACCOUNT_ID}:${api_id}/${ENVIRONMENT}/*" \
        --region "${AWS_REGION}" || echo "⚠️ Permission may already exist"
    
    echo "✅ Function route added successfully"
    echo "🌐 Function endpoint: https://${api_id}.execute-api.${AWS_REGION}.amazonaws.com${route_path}"
}

# Function to deploy shared HTTP API
deploy_shared_http_api() {
    local api_id=$1
    
    echo "Deploying shared HTTP API..."
    
    # Create stage
    local stage_exists=$(aws apigatewayv2 get-stages --api-id "${api_id}" --query "Items[?StageName=='${ENVIRONMENT}'].StageName" --output text)
    
    if [[ -z "${stage_exists}" || "${stage_exists}" == "None" ]]; then
        echo "Creating stage: ${ENVIRONMENT}"
        aws apigatewayv2 create-stage \
            --api-id "${api_id}" \
            --stage-name "${ENVIRONMENT}" \
            --auto-deploy
    else
        echo "Stage ${ENVIRONMENT} already exists"
    fi
    
    # Deploy the API to the stage
    echo "Deploying API to stage: ${ENVIRONMENT}"
    local deployment_id=$(aws apigatewayv2 create-deployment \
        --api-id "${api_id}" \
        --description "Deployment for ${ENVIRONMENT} environment" \
        --query 'DeploymentId' --output text)
    
    echo "✅ Deployment created with ID: ${deployment_id}"
    
    # Wait for deployment to complete
    echo "⏳ Waiting for deployment to complete..."
    sleep 15
    
    # Verify stage is accessible
    echo "🔍 Verifying stage deployment..."
    local stage_info=$(aws apigatewayv2 get-stage --api-id "${api_id}" --stage-name "${ENVIRONMENT}" --query 'StageName' --output text)
    if [[ "${stage_info}" == "${ENVIRONMENT}" ]]; then
        echo "✅ Stage ${ENVIRONMENT} is deployed and accessible"
    else
        echo "❌ Stage deployment verification failed"
    fi
    
    echo "HTTP API deployed successfully"
    echo "HTTP API URL: https://${api_id}.execute-api.${AWS_REGION}.amazonaws.com/${ENVIRONMENT}"
    
    return 0
}

# Function to manage shared HTTP API for a Lambda function
manage_shared_http_api() {
    local function_name=$1
    local prefixed_function_name="${ENVIRONMENT}_${function_name}"
    
    echo "Managing shared HTTP API for ${prefixed_function_name}..."
    
    # Get or create shared HTTP API
    local api_id=$(get_or_create_shared_http_api)
    
    if [[ -z "${api_id}" ]]; then
        echo "Error: Failed to get or create HTTP API"
        return 1
    fi
    
    # Validate that the HTTP API exists and is accessible
    if ! aws apigatewayv2 get-api --api-id "${api_id}" >/dev/null 2>&1; then
        echo "Error: HTTP API ${api_id} is not accessible. Removing cached ID and retrying..."
        rm -f .api_gateway_id
        api_id=$(get_or_create_shared_http_api)
        
        if [[ -z "${api_id}" ]]; then
            echo "Error: Failed to get or create HTTP API after retry"
            return 1
        fi
    fi
    
    echo "Using HTTP API ID: ${api_id}"
    
    # Add function route to the shared HTTP API
    if ! add_function_route "${function_name}" "${prefixed_function_name}" "${api_id}"; then
        echo "Error: Failed to add function route"
        return 1
    fi
    
    # Deploy the HTTP API
    deploy_shared_http_api "${api_id}"

    sleep 10
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
    BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker build \
        --platform linux/amd64 \
        -t "${image_name}:${image_tag}" \
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
    local temp_dir
    temp_dir=$(mktemp -d)
    local build_dir="${temp_dir}/build"
    mkdir -p "${build_dir}"

    # Install dependencies into build directory
    if [[ -f "${function_dir}/requirements.txt" ]]; then
        echo "Installing Python dependencies..."
        pip install -r "${function_dir}/requirements.txt" \
            --target "${build_dir}" \
            --platform manylinux2014_x86_64 \
            --implementation cp \
            --python-version 3.12 \
            --only-binary=:all: \
            --upgrade
    fi

    # Copy function files (excluding venv and __pycache__) to build directory
    echo "Copying function files..."
    rsync -av --exclude='venv' --exclude='__pycache__' "${function_dir}/" "${build_dir}/" > /dev/null

    # Create ZIP file
    local zip_file="${temp_dir}/${function_name}.zip"
    echo "Creating ZIP package..."
    cd "${build_dir}"
    zip -r "${zip_file}" . -q
    cd - > /dev/null

    # Update Lambda function code
    echo "Updating Lambda function code with ZIP file..."
    aws lambda update-function-code \
        --function-name "${prefixed_function_name}" \
        --zip-file "fileb://${zip_file}"

    # Clean up
    echo "Cleaning up temporary files..."
    rm -rf "${temp_dir}"
}


# Function to check if Lambda function exists
check_function_exists() {
    local function_name=$1
    aws lambda get-function --function-name "${function_name}" >/dev/null 2>&1
    return $?
}

# Function to configure CloudWatch logging for Lambda function
configure_lambda_logging() {
    local function_name=$1
    
    echo "📊 Configuring CloudWatch logging for ${function_name}..."
    
    # Create log group if it doesn't exist
    local log_group_name="/aws/lambda/${function_name}"
    local log_group_exists=$(aws logs describe-log-groups --log-group-name-prefix "${log_group_name}" --query "logGroups[?logGroupName=='${log_group_name}'].logGroupName" --output text)
    
    if [[ -z "${log_group_exists}" || "${log_group_exists}" == "None" ]]; then
        echo "Creating CloudWatch log group: ${log_group_name}"
        aws logs create-log-group --log-group-name "${log_group_name}"
        
    else
        echo "CloudWatch log group already exists: ${log_group_name}"
    fi
    
    # Update Lambda function to include logging configuration
    echo "Updating Lambda function with logging configuration..."
    aws lambda update-function-configuration \
        --function-name "${function_name}" \
        --tracing-config Mode=Active || echo "⚠️ Tracing configuration may not be supported or already set"
    
    echo "✅ CloudWatch logging configured for ${function_name}"
    echo "📋 Log group: ${log_group_name}"
    echo "🔗 View logs: https://${AWS_REGION}.console.aws.amazon.com/cloudwatch/home?region=${AWS_REGION}#logsV2:log-groups/log-group/${log_group_name//\//\$252F}"
}

# Function to create Lambda function
create_lambda_function() {
    local function_name=$1
    local function_dir=$2
    local env_vars=$3
    local role_arn="arn:aws:iam::${AWS_ACCOUNT_ID}:role/LambdaAccess"

    echo "Creating new Lambda function: ${function_name}"

    if [[ -f "${function_dir}/Dockerfile" ]]; then
        # For Docker-based functions
        # First, build and push the image
        local image_name="${function_name#dev_}"  # Remove 'dev_' prefix
        local image_tag="${ENVIRONMENT}"
        
        # Ensure ECR repository exists
        aws ecr describe-repositories --repository-names "${image_name}" || \
            aws ecr create-repository --repository-name "${image_name}"
        
        # Login to ECR
        aws ecr get-login-password --region "${AWS_REGION}" | \
            docker login --username AWS --password-stdin "${ECR_REGISTRY}"
        
        # Build and push image
        echo "🐳 Building Docker image: ${image_name}:${image_tag}"
        BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker build \
            --platform linux/amd64 \
            -t "${image_name}:${image_tag}" \
            --build-arg FUNCTION_DIR="${function_name}" \
            -f "${function_dir}/Dockerfile" .

        echo "🐳 Pushing Docker image: ${image_name}:${image_tag}"
        docker tag "${image_name}:${image_tag}" "${ECR_REGISTRY}/${image_name}:${image_tag}"
        docker push "${ECR_REGISTRY}/${image_name}:${image_tag}"

        # Create Lambda function with container image
        echo "🚀 Creating Lambda function with image: ${ECR_REGISTRY}/${image_name}:${image_tag}"
        aws lambda create-function \
            --function-name "${function_name}" \
            --package-type Image \
            --code ImageUri="${ECR_REGISTRY}/${image_name}:${image_tag}" \
            --role "${role_arn}" \
            --environment "Variables=${env_vars}" \
            --timeout 900 \
            --memory-size 2048 || {
                echo "❌ Failed to create Lambda function"
                return 1
            }

        # Clean up local images
        docker rmi "${image_name}:${image_tag}" "${ECR_REGISTRY}/${image_name}:${image_tag}"
    else
        # For ZIP-based functions
        # Create temporary directory for packaging
        local temp_dir=$(mktemp -d)
        local zip_file="${temp_dir}/${function_name}.zip"
        
        # Copy function files (excluding venv)
        rsync -av --exclude='venv' "${function_dir}/" "${temp_dir}/"
        
        # Install dependencies
        if [[ -f "${function_dir}/requirements.txt" ]]; then
            pip install -r "${function_dir}/requirements.txt" -t "${temp_dir}/" --quiet
        fi
        
        # Create ZIP
        cd "${temp_dir}"
        zip -r "${zip_file}" . -q
        cd - > /dev/null
        
        # Create Lambda function with ZIP
        aws lambda create-function \
            --function-name "${function_name}" \
            --runtime python3.12 \
            --handler lambda_function.lambda_handler \
            --role "${role_arn}" \
            --environment "Variables=${env_vars}" \
            --timeout 900 \
            --memory-size 2048 \
            --zip-file "fileb://${zip_file}"
        
        # Clean up
        rm -rf "${temp_dir}"
    fi
    
    # Configure CloudWatch logging after function creation
    configure_lambda_logging "${function_name}"
}

# Function to build and deploy a Lambda function
deploy_function() {
    local function_name=$1
    local function_dir="functions/${function_name}"
    local prefixed_function_name="${ENVIRONMENT}_${function_name}"
    local image_name="${function_name}"
    local image_tag="${ENVIRONMENT}"
    
    # Check if function directory exists and has lambda_function.py
    if [[ ! -d "${function_dir}" ]] || [[ ! -f "${function_dir}/lambda_function.py" ]]; then
        echo "Skipping ${function_name}: Missing function directory or lambda_function.py"
        return
    fi
    
    echo "Deploying ${prefixed_function_name}..."
    echo "----------------------------------------"
    
    # Load environment variables
    local env_vars=$(load_env_vars "${function_name}")
    echo "Environment variables: ${env_vars}"
    
    # Check if function exists
    if ! check_function_exists "${prefixed_function_name}"; then
        echo "Lambda function ${prefixed_function_name} does not exist. Creating..."
        create_lambda_function "${prefixed_function_name}" "${function_dir}" "${env_vars}"
    else
        echo "Lambda function ${prefixed_function_name} exists. Updating..."
        # Update Lambda function with environment variables if not empty
        if [ "$env_vars" != "{}" ]; then
            echo "Updating Lambda function with environment variables..."
            aws lambda update-function-configuration \
                --function-name "${prefixed_function_name}" \
                --environment "Variables=${env_vars}"
        fi
        
        # Choose deployment method based on Dockerfile existence
        if [[ -f "${function_dir}/Dockerfile" ]]; then
            echo "Dockerfile found. Using Docker deployment..."
            deploy_with_docker "${function_name}" "${function_dir}" "${prefixed_function_name}" "${image_name}" "${image_tag}"
        else
            echo "No Dockerfile found. Using ZIP deployment..."
            deploy_with_zip "${function_name}" "${function_dir}" "${prefixed_function_name}"
        fi
        
        # Ensure CloudWatch logging is configured for existing functions
        configure_lambda_logging "${prefixed_function_name}"
    fi
    
    echo "${prefixed_function_name} deployed successfully"
    echo "----------------------------------------"
    
    # Manage HTTP API for this function
    manage_shared_http_api "${function_name}"
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
    echo "Function ${SPECIFIC_FUNCTION} deployed successfully with shared API Gateway endpoint"
    echo ""
    echo "📊 To view CloudWatch logs for this function:"
    echo "aws logs tail /aws/lambda/${ENVIRONMENT}_${SPECIFIC_FUNCTION} --follow"
    echo "Or visit: https://${AWS_REGION}.console.aws.amazon.com/cloudwatch/home?region=${AWS_REGION}#logsV2:log-groups/log-group/%252Faws%252Flambda%252F${ENVIRONMENT}_${SPECIFIC_FUNCTION}"
else
    echo "All functions deployed successfully with shared API Gateway endpoints"
    echo ""
    echo "📊 To view CloudWatch logs for all functions:"
    echo "aws logs tail /aws/lambda/${ENVIRONMENT}_* --follow"
fi
