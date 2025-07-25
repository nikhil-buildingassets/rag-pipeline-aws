import requests
from typing import Dict, Any, List, Optional
from utils import get_qdrant_client, get_db_connection
from qdrant_client.http.models import Filter, FieldCondition, MatchValue, SearchParams
from qdrant_client.models import ScoredPoint
import numpy as np
from constants import COLLECTION_NAME
from logger import logger
from psycopg2.extras import RealDictCursor
from cost_tracker import cost_tracker

class ContextResolver:
    """Resolves and fetches different types of context based on classification."""
    
    def __init__(self):
        self.openai_embedding_url = 'https://api.openai.com/v1/embeddings'
    
    def resolve_context(self, context_type: str, message: str, file_ids: List[str], 
                       building_id: int, org_id: int, user_email: str) -> Dict[str, Any]:
        """Resolve context based on the classification type."""
        try:
            if context_type == "file_context":
                return self._resolve_file_context(message, file_ids, org_id, building_id)
            elif context_type == "building_context":
                return self._resolve_building_context(building_id, org_id)
            elif context_type == "organization_context":
                return self._resolve_organization_context(org_id, user_email)
            elif context_type == "vector_context":
                return self._resolve_vector_context(message, org_id, building_id)
            elif context_type == "general":
                return self._resolve_general_context()
            else:
                logger.warning(f"Unknown context type: {context_type}")
                return self._resolve_general_context()
                
        except Exception as e:
            logger.error(f"Error resolving context: {str(e)}")
            return {"context": "", "error": str(e)}
    
    def _resolve_file_context(self, message: str, file_ids: List[str], org_id: int, building_id: int) -> Dict[str, Any]:
        """Resolve file-specific context using vector search."""
        try:
            if not file_ids:
                return {"context": "", "error": "No file IDs provided"}
            
            # Get embeddings for the query
            query_embedding = self._get_embedding(message)
            
            # Search for relevant chunks
            relevant_chunks = self._search_vector_store(
                query_embedding, org_id, building_id, file_ids
            )
            
            if not relevant_chunks:
                return {"context": "", "error": "No relevant content found"}
            
            # Format the context
            context_parts = []
            for chunk in relevant_chunks:
                context_parts.append(f"File: {chunk.get('file_name', 'Unknown')}")
                context_parts.append(f"Content: {chunk['text']}")
                if chunk.get('page'):
                    context_parts.append(f"Page: {chunk['page']}")
                context_parts.append("---")
            
            context = "\n".join(context_parts)
            
            return {
                "context": context,
                "chunks": relevant_chunks,
                "file_ids": file_ids,
                "context_type": "file_context"
            }
            
        except Exception as e:
            logger.error(f"Error resolving file context: {str(e)}")
            return {"context": "", "error": str(e)}
    
    def _resolve_building_context(self, building_id: int, org_id: int) -> Dict[str, Any]:
        """Resolve building-specific context from database."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Fetch building details
            cursor.execute("""
                SELECT * FROM buildings WHERE id = %s AND org_id = %s
            """, (building_id, org_id))
            building = cursor.fetchone()
            
            if not building:
                return {"context": "", "error": "Building not found"}
            
            # Fetch recent measures
            cursor.execute("""
                SELECT * FROM measures 
                WHERE building_id = %s AND org_id = %s 
                ORDER BY created_at DESC LIMIT 10
            """, (building_id, org_id))
            measures = cursor.fetchall()
            
            # Fetch recent energy data
            cursor.execute("""
                SELECT * FROM espm_data 
                WHERE building_id = %s AND org_id = %s 
                ORDER BY start_date DESC LIMIT 12
            """, (building_id, org_id))
            energy_data = cursor.fetchall()
            
            # Fetch recent bills
            cursor.execute("""
                SELECT * FROM bills 
                WHERE building_id = %s AND org_id = %s 
                ORDER BY bill_date DESC LIMIT 12
            """, (building_id, org_id))
            bills = cursor.fetchall()
            
            # Format building context
            context_parts = [
                f"Building: {building['building_name']}",
                f"Address: {building.get('address', 'Unknown')}",
                f"Type: {building.get('building_type', 'Unknown')}",
                f"Size: {building.get('gross_floor_area', 'Unknown')} sq ft",
                f"Year Built: {building.get('year_built', 'Unknown')}"
            ]
            
            if measures:
                context_parts.append(f"\nRecent Measures ({len(measures)}):")
                for measure in measures[:5]:
                    context_parts.append(f"- {measure['measure_name']}: {measure['status']}")
            
            if energy_data:
                context_parts.append(f"\nRecent Energy Data ({len(energy_data)} entries):")
                for data in energy_data[:3]:
                    context_parts.append(f"- {data['start_date']}: {data.get('usage_quantity', 'N/A')} {data.get('usage_units', 'units')}")
            
            if bills:
                context_parts.append(f"\nRecent Bills ({len(bills)} entries):")
                for bill in bills[:3]:
                    context_parts.append(f"- {bill['bill_date']}: {bill['bill_type']} - ${bill.get('amount', 'N/A')}")
            
            context = "\n".join(context_parts)
            
            return {
                "context": context,
                "building": building,
                "measures": measures,
                "energy_data": energy_data,
                "bills": bills,
                "context_type": "building_context"
            }
            
        except Exception as e:
            logger.error(f"Error resolving building context: {str(e)}")
            return {"context": "", "error": str(e)}
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
    
    def _resolve_organization_context(self, org_id: int, user_email: str) -> Dict[str, Any]:
        """Resolve organization-level context."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Fetch organization details
            cursor.execute("""
                SELECT * FROM organizations WHERE id = %s
            """, (org_id,))
            org = cursor.fetchone()
            
            if not org:
                return {"context": "", "error": "Organization not found"}
            
            # Fetch all buildings in the organization
            cursor.execute("""
                SELECT id, building_name, building_type, gross_floor_area, year_built
                FROM buildings WHERE org_id = %s ORDER BY building_name
            """, (org_id,))
            buildings = cursor.fetchall()
            
            # Fetch organization-wide metrics
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_buildings,
                    SUM(gross_floor_area) as total_area,
                    AVG(year_built) as avg_year_built
                FROM buildings WHERE org_id = %s
            """, (org_id,))
            metrics = cursor.fetchone()
            
            # Format organization context
            context_parts = [
                f"Organization: {org['org_name']}",
                f"Admin: {org['admin_email']}",
                f"Address: {org.get('address', 'Unknown')}"
            ]
            
            if buildings:
                context_parts.append(f"\nBuildings ({len(buildings)}):")
                for building in buildings[:10]:  # Limit to 10 buildings
                    context_parts.append(f"- {building['building_name']}: {building.get('building_type', 'Unknown')}")
            
            if metrics:
                context_parts.append(f"\nPortfolio Summary:")
                context_parts.append(f"- Total Buildings: {metrics['total_buildings']}")
                if metrics['total_area']:
                    context_parts.append(f"- Total Area: {metrics['total_area']:,.0f} sq ft")
                if metrics['avg_year_built']:
                    context_parts.append(f"- Average Year Built: {metrics['avg_year_built']:.0f}")
            
            context = "\n".join(context_parts)
            
            return {
                "context": context,
                "organization": org,
                "buildings": buildings,
                "metrics": metrics,
                "context_type": "organization_context"
            }
            
        except Exception as e:
            logger.error(f"Error resolving organization context: {str(e)}")
            return {"context": "", "error": str(e)}
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
    
    def _resolve_general_context(self) -> Dict[str, Any]:
        """Resolve general context for general questions."""
        return {
            "context": "You are a helpful building management assistant. You can help with questions about building operations, energy efficiency, maintenance, and general building management topics.",
            "context_type": "general"
        }
    
    def _resolve_vector_context(self, message: str, org_id: int, building_id: int) -> Dict[str, Any]:
        """Resolve vector context by searching all documents for the building/organization."""
        try:
            # Get embeddings for the query
            query_embedding = self._get_embedding(message)
            
            # Search for relevant chunks across all documents for this building/org
            relevant_chunks = self._search_vector_store_all_docs(
                query_embedding, org_id, building_id
            )
            
            if not relevant_chunks:
                return {"context": "", "error": "No relevant content found in vector store"}
            
            # Format the context
            context_parts = []
            for chunk in relevant_chunks:
                context_parts.append(f"Source: {chunk.get('file_name', 'Unknown Document')}")
                context_parts.append(f"Content: {chunk['text']}")
                if chunk.get('page'):
                    context_parts.append(f"Page: {chunk['page']}")
                context_parts.append("---")
            
            context = "\n".join(context_parts)
            
            return {
                "context": context,
                "chunks": relevant_chunks,
                "context_type": "vector_context",
                "search_query": message
            }
            
        except Exception as e:
            logger.error(f"Error resolving vector context: {str(e)}")
            return {"context": "", "error": str(e)}
    
    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for text using OpenAI API."""
        try:
            from utils import get_openai_api_key
            
            # Prepare request data for cost tracking
            request_data = {
                "input": text,
                "model": "text-embedding-3-small"
            }
            
            response = requests.post(
                self.openai_embedding_url,
                headers={
                    "Authorization": f"Bearer {get_openai_api_key()}",
                    "Content-Type": "application/json"
                },
                json=request_data,
                timeout=10
            )
            
            if not response.ok:
                raise Exception(f"Embedding API error: {response.status_code}")
            
            result = response.json()
            
            # Log cost for embedding
            cost_tracker.log_api_call(
                api_type="embedding",
                model="text-embedding-3-small",
                usage=result.get('usage', {}),
                request_data=request_data,
                response_data=result
            )
            
            return result['data'][0]['embedding']
            
        except Exception as e:
            logger.error(f"Error getting embedding: {str(e)}")
            raise
    
    def _search_vector_store(self, query_embedding: List[float], org_id: int, 
                           building_id: int, file_ids: List[str], top_k: int = 5) -> List[Dict]:
        """Search vector store for relevant chunks."""
        try:
            q_client = get_qdrant_client()
            
            # Build filters
            must_filters = [
                FieldCondition(key="org_id", match=MatchValue(value=org_id)),
                FieldCondition(key="building_id", match=MatchValue(value=building_id))
            ]
            
            # Add file ID filters if provided
            if file_ids:
                file_filters = []
                for file_id in file_ids:
                    file_filters.append(FieldCondition(key="file_id", match=MatchValue(value=file_id)))
                must_filters.append(Filter(should=file_filters))
            
            q_filter = Filter(must=must_filters)
            
            # Search
            results: List[ScoredPoint] = q_client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_embedding,
                query_filter=q_filter,
                limit=top_k,
                with_payload=["text", "chunk_index", "file_id"],
                with_vectors=False,
                search_params=SearchParams(hnsw_ef=128, exact=False)
                # hnsw_ef Value	Effect
                # 32–64	Faster, less accurate
                # 128–256	Slower, more accurate
                # Default	~top_k * 10
            )
            
            # Format results
            chunks = []
            for points in results:
                for point in points[1]:
                    chunks.append({
                        "text": point.payload["text"],
                        "score": point.score,
                        "chunk_index": point.payload.get("chunk_index"),
                        "file_id": point.payload.get("file_id")
                    })
            
            return chunks
            
        except Exception as e:
            logger.error(f"Error searching vector store: {str(e)}")
            return []

    def _search_vector_store_all_docs(self, query_embedding: List[float], org_id: int, 
                                    building_id: int, top_k: int = 8) -> List[Dict]:
        """Search vector store for relevant chunks across all documents for building/org."""
        try:
            q_client = get_qdrant_client()
            
            # Build filters - only filter by org_id and building_id, no file_id restriction
            must_filters = [
                FieldCondition(key="org_id", match=MatchValue(value=org_id)),
                FieldCondition(key="building_id", match=MatchValue(value=building_id))
            ]
            
            q_filter = Filter(must=must_filters)
            
            # Search across all documents
            results: List[ScoredPoint] = q_client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_embedding,
                query_filter=q_filter,
                limit=top_k,
                with_payload=["text", "chunk_index", "file_id"],
                with_vectors=False,
                search_params=SearchParams(hnsw_ef=128, exact=False)
                # hnsw_ef Value	Effect
                # 32–64	Faster, less accurate
                # 128–256	Slower, more accurate
                # Default	~top_k * 10
            )
            
            # Format results
            chunks = []
            for points in results:
                for point in points[1]:
                    chunks.append({
                        "text": point.payload["text"],
                        "score": point.score,
                        "chunk_index": point.payload.get("chunk_index"),
                        "file_id": point.payload.get("file_id")
                    })
            
            return chunks
            
        except Exception as e:
            logger.error(f"Error searching vector store for all docs: {str(e)}")
            return []
