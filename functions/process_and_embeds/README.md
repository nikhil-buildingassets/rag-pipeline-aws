# Process and Embed Lambda Function

This Lambda function processes PDF files and generates embeddings using a pre-downloaded SentenceTransformer model for optimal performance.

## 🚀 Performance Optimizations

### Pre-downloaded Model
- The SentenceTransformer model (`all-MiniLM-L6-v2`) is pre-downloaded during the Docker build process
- This eliminates cold start delays caused by model downloading
- Significantly improves Lambda function startup time

### Sliding Window Chunking
- Uses an efficient sliding window approach for text chunking
- Configurable chunk size and overlap parameters
- Consistent chunk sizes for better embedding quality

## 📦 Building the Docker Image

### Option 1: Using the build script (Recommended)
```bash
cd functions/process_and_embeds
chmod +x build.sh
./build.sh
```

### Option 2: Manual Docker build
```bash
cd functions/process_and_embeds
docker build -t process-and-embeds:latest .
```

## 🔧 Configuration

### Chunking Parameters
You can configure the chunking behavior by passing parameters in the Lambda event:

```json
{
  "file_content": "...",
  "window_size": 512,  // Number of words per chunk (default: 512)
  "overlap": 50        // Number of overlapping words (default: 50)
}
```

### Model Configuration
The model is automatically loaded from the local path `./my_model`. If not found, it will download and save it for future use.

## 📊 Performance Benefits

### Before Optimization
- Cold start: ~30-60 seconds (model download)
- Memory usage: High during model download
- Network dependency: Required for every cold start

### After Optimization
- Cold start: ~5-10 seconds (model already available)
- Memory usage: Consistent and predictable
- Network dependency: Only during build time

## 🧪 Testing

### Local Testing
```bash
# Build the image
docker build -t process-and-embeds:latest .

# Run locally
docker run -p 9000:8080 process-and-embeds:latest

# Test with curl
curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" -d '{
  "file_content": "base64_encoded_pdf_content",
  "window_size": 512,
  "overlap": 50
}'
```

## 📁 File Structure

```
process_and_embeds/
├── main.py              # Main Lambda function
├── download_model.py    # Script to download and save model
├── Dockerfile          # Multi-stage Docker build
├── requirements.txt    # Python dependencies
├── build.sh           # Build automation script
└── README.md          # This file
```

## 🔄 Deployment

1. Build the Docker image using the build script
2. Push to Amazon ECR
3. Update your Lambda function to use the new container image

## 📈 Monitoring

Monitor the following metrics to verify performance improvements:
- Cold start duration
- Memory usage
- Network activity during cold starts
- Overall function execution time 