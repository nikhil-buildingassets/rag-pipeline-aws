# Stage 1: Build layer with dependencies
FROM public.ecr.aws/lambda/python:3.12 AS builder

WORKDIR /build

COPY functions/pre_upload_check/requirements.txt .

RUN pip install --upgrade pip \
    && pip install --no-cache-dir --target python -r requirements.txt

# Stage 3: Final image
FROM public.ecr.aws/lambda/python:3.12

COPY --from=builder /build/python ${LAMBDA_TASK_ROOT}

COPY functions/pre_upload_check/lambda_function.py ${LAMBDA_TASK_ROOT}

# Command to run the Lambda function
CMD [ "lambda_function.lambda_handler" ]
