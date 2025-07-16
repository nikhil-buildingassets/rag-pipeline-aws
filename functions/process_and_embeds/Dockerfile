# Stage 1: Build layer with dependencies
FROM public.ecr.aws/lambda/python:3.12 AS builder

WORKDIR /build

COPY functions/process_and_embeds/requirements.txt .

RUN pip install --upgrade pip \
    && pip install --no-cache-dir --target python -r requirements.txt

# Stage 2: Download model
FROM public.ecr.aws/lambda/python:3.12 AS model-downloader

WORKDIR /model

# Copy requirements and install dependencies
COPY functions/process_and_embeds/requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the download script and run it
COPY functions/process_and_embeds/download_model.py .
RUN python download_model.py

# Stage 3: Final image
FROM public.ecr.aws/lambda/python:3.12

COPY --from=builder /build/python ${LAMBDA_TASK_ROOT}

# Copy the pre-downloaded model
COPY --from=model-downloader /model/my_model ${LAMBDA_TASK_ROOT}/my_model

COPY functions/process_and_embeds/main.py ${LAMBDA_TASK_ROOT}

# Command to run the Lambda function
CMD [ "main.lambda_handler" ]
