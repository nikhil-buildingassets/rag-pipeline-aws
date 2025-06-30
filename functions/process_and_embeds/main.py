# takes file byte data and process the file
# extract, clean, and embedd, vectorize and return vectors

import json
import os
from typing import List, Dict, Optional, Any
import fitz  # PyMuPDF
from nltk.tokenize import sent_tokenize
import nltk
from sentence_transformers import SentenceTransformer
import numpy as np
import logging

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Set tokenizers parallelism to avoid warnings
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Download required NLTK data
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda handler for processing PDF and generating embeddings."""
    try:
        # Extract parameters from event
        pdf_content = event.get('pdf_content')
        if not pdf_content:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'pdf_content is required in the event payload'
                })
            }

        # Initialize processor and process PDF
        processor = ProcessAndEmbed()
        result = processor.process_pdf_bytes(pdf_content)

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
        self.embeddings: Optional[np.ndarray] = None
        
        # Initialize the model
        try:
            self.model = SentenceTransformer('all-MiniLM-L6-v2')  # Default model
            logger.info(f"Initialized model: all-MiniLM-L6-v2")
        except Exception as e:
            logger.error(f"Failed to load model: {str(e)}")
            raise

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

    def extract_text_from_pdf_bytes(self, pdf_content: bytes) -> List[Dict]:
        """Extract text from PDF bytes."""
        try:
            logger.info("Processing PDF from bytes")
            doc = fitz.open(stream=pdf_content, filetype="pdf")
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
            logger.error(f"Error extracting text from PDF: {str(e)}")
            raise
        finally:
            if 'doc' in locals():
                doc.close()

    def chunk_text(self, text: str) -> List[str]:
        """Chunk text optimized for semantic search."""
        # Split into sentences first
        sentences = sent_tokenize(text)
        chunks = []
        current_chunk = []
        current_length = 0
        max_chunk_size = 512  # Default chunk size
        chunk_overlap = 50    # Default overlap size
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            sentence_length = len(sentence.split())
            
            # If adding this sentence would exceed chunk size
            if current_length + sentence_length > max_chunk_size:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                current_chunk = [sentence]
                current_length = sentence_length
            else:
                current_chunk.append(sentence)
                current_length += sentence_length
        
        # Add the last chunk
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        
        # Create overlapping chunks for better context
        if chunk_overlap > 0 and len(chunks) > 1:
            overlapped_chunks = []
            for i in range(len(chunks)):
                if i > 0:
                    # Add overlap from previous chunk
                    prev_words = chunks[i-1].split()[-chunk_overlap:]
                    current_words = chunks[i].split()
                    overlapped_chunks.append(" ".join(prev_words + current_words))
                else:
                    overlapped_chunks.append(chunks[i])
            chunks = overlapped_chunks
        
        return chunks

    def create_chunks(self) -> List[Dict]:
        """Create chunks with metadata preservation."""
        self.chunked_docs = []
        for entry in self.text_chunks:
            chunks = self.chunk_text(entry["text"])
            for i, chunk in enumerate(chunks):
                self.chunked_docs.append({
                    "page": entry["page"],
                    "text": chunk,
                    "chunk_index": i,
                    "total_chunks": len(chunks)
                })
        
        logger.info(f"Created {len(self.chunked_docs)} chunks")
        return self.chunked_docs

    def generate_embeddings(self) -> np.ndarray:
        """Generate embeddings with batching and progress tracking."""
        texts = [entry["text"] for entry in self.chunked_docs]
        batch_size = 32
        
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = self.model.encode(batch, show_progress_bar=True, normalize_embeddings=True)
            all_embeddings.append(batch_embeddings)
            
        self.embeddings = np.vstack(all_embeddings)
        logger.info(f"Generated embeddings of shape {self.embeddings.shape}")
        return self.embeddings

    def process_pdf_bytes(self, pdf_content: bytes) -> Dict[str, Any]:
        """Process PDF bytes and return chunks and embeddings."""
        try:
            # Extract text from PDF
            logger.info("Extracting text from PDF...")
            self.extract_text_from_pdf_bytes(pdf_content)
            
            if not self.text_chunks:
                raise ValueError("No text was extracted from the PDF!")
            
            # Create semantic chunks
            logger.info("Creating semantic chunks...")
            self.create_chunks()
            
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
                    'pdf_size_bytes': len(pdf_content)
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing PDF: {str(e)}")
            return {
                'status': 'error',
                'error': str(e)
            }
