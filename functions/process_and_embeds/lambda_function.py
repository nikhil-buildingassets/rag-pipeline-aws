import json
import os
from typing import List, Dict, Any
import fitz  # PyMuPDF
import requests
import numpy as np
import logging
import boto3
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Constants
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')
SECRET_NAME = f'{ENVIRONMENT}-buildingassets-secrets'
OPENAI_API_URL = "https://api.openai.com/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-3-small"

s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')

def get_openai_api_key():
    """Get OpenAI API key from Secrets Manager."""
    try:
        secret_response = secrets_client.get_secret_value(
            SecretId=SECRET_NAME
        )
        credentials = json.loads(secret_response['SecretString'])
        return credentials['OPENAI_API_KEY']
    except Exception as e:
        logger.error(f"Error getting OpenAI API key: {str(e)}")
        raise

def get_openai_embedding(text: str) -> np.ndarray:
    """Get embedding from OpenAI API for a single text."""
    OPENAI_API_KEY = get_openai_api_key()

    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY environment variable is required")
    
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "input": text,
        "model": EMBEDDING_MODEL
    }
    
    try:
        response = requests.post(OPENAI_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        embedding = result['data'][0]['embedding']
        return np.array(embedding)
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling OpenAI API: {str(e)}")
        raise

def get_openai_embeddings_batch(texts: List[str]) -> np.ndarray:
    """Get embeddings from OpenAI API for a batch of texts."""
    OPENAI_API_KEY = get_openai_api_key()

    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY environment variable is required")
    
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "input": texts,
        "model": EMBEDDING_MODEL
    }
    
    try:
        response = requests.post(OPENAI_API_URL, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        embeddings = [item['embedding'] for item in result['data']]
        return np.array(embeddings)
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling OpenAI API: {str(e)}")
        raise

def get_file_from_s3(file_url: str) -> Tuple[bytes, str]:
    """Get file content directly from S3 into memory."""
    logger.info(f"Fetching file content from {file_url}")
    
    try:
        # Parse the S3 URL
        parsed_url = urlparse(file_url)
        bucket = parsed_url.netloc.split('.')[0]
        key = parsed_url.path.lstrip('/')
        
        # Get the object from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        # Read the content into memory
        file_content = response['Body'].read()
        filename = Path(key).name
        logger.info(f"Successfully fetched file content, size: {len(file_content)} bytes")
        return file_content, filename
    except Exception as e:
        logger.error(f"Error fetching file from S3: {str(e)}")
        raise


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda handler for processing files and generating embeddings."""
    try:
        # Extract parameters from event
        embedding_only = event.get('embedding_only', False)
        window_size = event.get('window_size', 512)  # Default chunk size
        overlap = event.get('overlap', 50)  # Default overlap size

        file_url = event.get('file_url')
        file_content, filename = get_file_from_s3(file_url)

        logger.info(f"File url: {file_url}, filename: {filename}")
        
        if not file_content:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'file content is required in the event payload'
                })
            }

        # Initialize processor
        processor = ProcessAndEmbed()

        if embedding_only:
            # For embedding only, we expect the content to be text
            try:
                # Try to decode as text first
                if isinstance(file_content, bytes):
                    text_content = file_content.decode('utf-8')
                else:
                    text_content = file_content
                
                # Generate embedding for the text content
                embedding = processor.generate_single_embedding(text_content)
                
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'status': 'success',
                        'embedding': embedding.tolist()
                    })
                }
            except UnicodeDecodeError:
                # If decode fails, treat as file
                logger.info("Content appears to be binary, processing as file...")
                result = processor.process_file_bytes(file_content)
                if result['status'] == 'success' and result.get('embeddings'):
                    # Return the first embedding if multiple were generated
                    return {
                        'statusCode': 200,
                        'body': json.dumps({
                            'status': 'success',
                            'embedding': result['embeddings'][0]
                        })
                    }
                return {
                    'statusCode': 500,
                    'body': json.dumps(result)
                }
        else:
            result = processor.process_file_bytes(file_content, window_size=window_size, overlap=overlap)
            return {
                'statusCode': 200 if result['status'] == 'success' else 500,
                'body': json.dumps(result)
            }

    except Exception as e:
        logger.error(f"Error in lambda handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'error',
                'message': str(e)
            })
        }

class ProcessAndEmbed:
    def __init__(self):
        # Initialize basic attributes
        self.text_chunks: List[Dict] = []
        self.chunked_docs: List[Dict] = []
        self.embeddings: np.ndarray | None = None

    def _clean_text(self, text: str) -> str:
        """Clean and normalize extracted text."""
        import re
        # Fix line breaks and spacing
        text = re.sub(r'\s*\n\s*', ' ', text)  # Convert line breaks to spaces
        text = re.sub(r'[ \t]+', ' ', text)    # Normalize spaces
        
        # Join hyphenated words that were split across lines
        text = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', text)
        
        # Fix common OCR and formatting issues
        text = text.replace('—', '-')  # Normalize dashes
        text = text.replace('–', '-')  # Normalize dashes
        
        # Remove repeated punctuation
        text = re.sub(r'([.,!?])\1+', r'\1', text)
        
        # Fix spacing around punctuation
        text = re.sub(r'\s+([.,!?])', r'\1', text)
        text = re.sub(r'([.,!?])(?!\s|$)', r'\1 ', text)
        
        # Final cleanup
        text = re.sub(r'\s+', ' ', text)  # Remove multiple spaces
        return text.strip()

    def generate_single_embedding(self, text: str) -> np.ndarray:
        """Generate embedding for a single text string."""
        cleaned_text = self._clean_text(text)
        embedding = get_openai_embedding(cleaned_text)
        return embedding

    def extract_text_from_file_bytes(self, file_content: bytes) -> List[Dict]:
        """Extract text from file bytes."""
        try:
            logger.info("Processing file from bytes")
            doc = fitz.open(stream=file_content, filetype="file")
            self.text_chunks = []
            
            for page_num, page in enumerate(doc):
                # Extract text with layout preservation
                text_dict = page.get_text("dict")
                text_blocks = []
                
                # Process text blocks while preserving structure
                for block in text_dict.get("blocks", []):
                    if block.get("type") == 0:  # Text block
                        block_text = []
                        for line in block.get("lines", []):
                            line_text = " ".join(span.get("text", "") for span in line.get("spans", []))
                            if line_text.strip():
                                block_text.append(line_text)
                        if block_text:
                            text_blocks.append("\n".join(block_text))
                
                if text_blocks:
                    # Combine blocks with proper spacing
                    combined_text = "\n\n".join(text_blocks)
                    cleaned_text = self._clean_text(combined_text)
                    
                    # Store with metadata
                    self.text_chunks.append({
                        "page": page_num + 1,
                        "text": cleaned_text,
                        "word_count": len(cleaned_text.split())
                    })
            
            logger.info(f"Extracted text from {len(self.text_chunks)} pages")
            return self.text_chunks
            
        except Exception as e:
            logger.error(f"Error extracting text from file: {str(e)}")
            raise
        finally:
            if 'doc' in locals():
                doc.close()

    def chunk_text(self, text: str, window_size: int = 512, overlap: int = 50) -> List[str]:
        """Chunk text using sliding window approach for optimal semantic search."""
        # Clean the text first
        cleaned_text = self._clean_text(text)
        words = cleaned_text.split()
        
        # Handle edge cases
        if len(words) <= window_size:
            return [cleaned_text]
        
        chunks = []
        start = 0
        
        while start < len(words):
            end = min(start + window_size, len(words))
            chunk_words = words[start:end]
            chunk_text = " ".join(chunk_words)
            
            # Only add non-empty chunks
            if chunk_text.strip():
                chunks.append(chunk_text)
            
            # Slide forward with overlap
            start += window_size - overlap
            
            # Prevent infinite loop if overlap >= window_size
            if start >= len(words):
                break
        
        return chunks

    def create_chunks(self, window_size: int = 512, overlap: int = 50) -> List[Dict]:
        """Create chunks with metadata preservation using sliding window approach."""
        self.chunked_docs = []
        total_chunks = 0
        
        for entry in self.text_chunks:
            chunks = self.chunk_text(entry["text"], window_size=window_size, overlap=overlap)
            for i, chunk in enumerate(chunks):
                self.chunked_docs.append({
                    "page": entry["page"],
                    "text": chunk,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "word_count": len(chunk.split()),
                    "chunk_size": window_size,
                    "overlap": overlap
                })
            total_chunks += len(chunks)
        
        logger.info(f"Created {len(self.chunked_docs)} chunks using sliding window (size={window_size}, overlap={overlap})")
        logger.info(f"Average chunk size: {sum(len(chunk['text'].split()) for chunk in self.chunked_docs) / len(self.chunked_docs):.1f} words")
        return self.chunked_docs

    def generate_embeddings(self) -> np.ndarray:
        """Generate embeddings with batching and progress tracking."""
        texts = [entry["text"] for entry in self.chunked_docs]
        batch_size = 32
        
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = get_openai_embeddings_batch(batch)
            all_embeddings.append(batch_embeddings)
            
        self.embeddings = np.vstack(all_embeddings)
        logger.info(f"Generated embeddings of shape {self.embeddings.shape}")
        return self.embeddings

    def process_file_bytes(self, file_content: bytes, window_size: int = 512, overlap: int = 50) -> Dict[str, Any]:
        """Process file bytes and return chunks and embeddings using sliding window chunking."""
        try:
            # Extract text from file
            logger.info("Extracting text from file...")
            self.extract_text_from_file_bytes(file_content)
            
            if not self.text_chunks:
                raise ValueError("No text was extracted from the file!")
            
            # Create semantic chunks using sliding window
            logger.info(f"Creating semantic chunks with window_size={window_size}, overlap={overlap}...")
            self.create_chunks(window_size=window_size, overlap=overlap)
            
            # Generate embeddings
            logger.info("Generating embeddings...")
            self.generate_embeddings()
            
            # Return processing results
            return {
                'status': 'success',
                'chunks': self.chunked_docs,
                'embeddings': self.embeddings.tolist(),  # Convert to list for JSON serialization
                'stats': {
                    'num_chunks': len(self.chunked_docs),
                    'embedding_dim': self.embeddings.shape[1] if self.embeddings is not None else None,
                    'file_size_bytes': len(file_content),
                    'chunking_config': {
                        'window_size': window_size,
                        'overlap': overlap
                    }
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing file: {str(e)}")
            return {
                'status': 'error',
                'error': str(e)
            }
