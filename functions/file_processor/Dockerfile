# Use AWS Lambda Python runtime as base image
FROM public.ecr.aws/lambda/python:3.12

# Copy requirements file
COPY functions/file_processor/requirements.txt ${LAMBDA_TASK_ROOT}

# Install Python dependencies
RUN pip install -r requirements.txt --no-cache-dir

# Copy function code
COPY functions/file_processor/main.py ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler
CMD [ "main.lambda_handler" ] 