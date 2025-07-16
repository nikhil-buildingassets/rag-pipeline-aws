#!/usr/bin/env python3
"""
Script to download and save the SentenceTransformer model locally.
This should be run before building the Docker image to pre-download the model.
"""

import os
import sys
from sentence_transformers import SentenceTransformer
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def download_model():
    """Download and save the SentenceTransformer model locally."""
    model_name = 'all-MiniLM-L6-v2'
    model_dir = './my_model'
    
    try:
        logger.info(f"Downloading model: {model_name}")
        
        # Download the model
        model = SentenceTransformer(model_name)
        
        # Save the model locally
        logger.info(f"Saving model to: {model_dir}")
        model.save(model_dir)
        
        logger.info("Model downloaded and saved successfully!")
        
        # Test the saved model
        logger.info("Testing saved model...")
        test_model = SentenceTransformer(model_dir)
        test_text = "This is a test sentence."
        embedding = test_model.encode([test_text])
        logger.info(f"Test embedding shape: {embedding.shape}")
        logger.info("Model test successful!")
        
        return True
        
    except Exception as e:
        logger.error(f"Error downloading model: {str(e)}")
        return False

if __name__ == "__main__":
    success = download_model()
    sys.exit(0 if success else 1) 