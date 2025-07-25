# Stage 1: Build layer with dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

COPY functions/building_chat/requirements.txt .

RUN pip install --no-cache-dir --target python -r requirements.txt \
    && find python -type d -name "__pycache__" -exec rm -r {} + \
    && find python -type f -name "*.pyc" -delete

# Stage 3: Final image
FROM public.ecr.aws/lambda/python:3.12

COPY --from=builder /build/python ${LAMBDA_TASK_ROOT}

COPY functions/building_chat/ ${LAMBDA_TASK_ROOT}

# Command to run the Lambda function
CMD [ "lambda_function.lambda_handler" ]
