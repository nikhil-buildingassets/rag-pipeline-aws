# Use AWS Lambda Python runtime as base image
FROM public.ecr.aws/lambda/python:3.12

# Install system dependencies for PyMuPDF
RUN yum install -y \
    mupdf \
    mupdf-tools \
    && yum clean all

# Copy requirements file
COPY functions/process_and_embeds/requirements.txt ${LAMBDA_TASK_ROOT}

# Install Python dependencies
RUN pip install -r requirements.txt --no-cache-dir

# Copy function code
COPY functions/process_and_embeds/main.py ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler
CMD [ "main.lambda_handler" ] 