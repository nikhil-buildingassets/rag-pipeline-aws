# Use AWS Lambda Python runtime as base image
FROM public.ecr.aws/lambda/python:3.12

# Install system dependencies for FAISS
RUN yum install -y \
    gcc \
    gcc-c++ \
    make \
    && yum clean all

# Copy requirements file
COPY functions/rag_pipeline/requirements.txt ${LAMBDA_TASK_ROOT}

# Install Python dependencies
RUN pip install -r requirements.txt --no-cache-dir

# Copy function code
COPY functions/rag_pipeline/main.py ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler
CMD [ "main.lambda_handler" ] 