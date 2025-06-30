FROM public.ecr.aws/lambda/python:3.9

# Copy requirements and install dependencies
COPY functions/pre_upload_check/requirements.txt ./
RUN pip install -r requirements.txt

# Copy function code
COPY functions/pre_upload_check/main.py ./

# Set the CMD to your handler
CMD [ "main.lambda_handler" ] 