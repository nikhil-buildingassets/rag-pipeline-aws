#!/bin/bash

# Exit on error
set -e

# AWS account and region configuration
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=$(aws configure get region)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Function to build and deploy a Lambda function
deploy_function() {
    local function_name=$1
    local function_dir="functions/${function_name}"
    local image_name="${function_name}-lambda"
    local image_tag="latest"
    
    # Check if function directory contains required files
    if [[ ! -f "${function_dir}/Dockerfile" ]] || [[ ! -f "${function_dir}/main.py" ]]; then
        echo "Skipping ${function_name}: Missing required files (Dockerfile or main.py)"
        return
    fi
    
    echo "Deploying ${function_name}..."
    echo "----------------------------------------"
    
    # Ensure ECR repository exists
    echo "Checking ECR repository..."
    aws ecr describe-repositories --repository-names "${image_name}" || \
        aws ecr create-repository --repository-name "${image_name}"
    
    # Login to ECR
    echo "Logging into ECR..."
    aws ecr get-login-password --region "${AWS_REGION}" | \
        docker login --username AWS --password-stdin "${ECR_REGISTRY}"
    
    # Build Docker image
    echo "Building Docker image for ${function_name}..."
    docker build -t "${image_name}:${image_tag}" \
        --build-arg FUNCTION_DIR="${function_name}" \
        -f "${function_dir}/Dockerfile" .
    
    # Tag and push image to ECR
    echo "Pushing image to ECR..."
    docker tag "${image_name}:${image_tag}" "${ECR_REGISTRY}/${image_name}:${image_tag}"
    docker push "${ECR_REGISTRY}/${image_name}:${image_tag}"
    
    # Update Lambda function
    echo "Updating Lambda function..."
    aws lambda update-function-code \
        --function-name "${function_name}" \
        --image-uri "${ECR_REGISTRY}/${image_name}:${image_tag}"
    
    # Clean up local Docker images
    echo "Cleaning up local images..."
    docker rmi "${image_name}:${image_tag}" "${ECR_REGISTRY}/${image_name}:${image_tag}"
    
    echo "${function_name} deployed successfully"
    echo "----------------------------------------"
}

# Get list of all function directories
echo "Discovering Lambda functions..."
functions=()
for dir in functions/*/; do
    # Remove trailing slash and 'functions/' prefix
    function_name=$(basename "${dir}")
    functions+=("${function_name}")
done

# Print discovered functions
echo "Found ${#functions[@]} functions to deploy:"
printf '%s\n' "${functions[@]}"
echo "----------------------------------------"

# Deploy each discovered function
for function_name in "${functions[@]}"; do
    deploy_function "${function_name}"
done

echo "All functions deployed successfully"
