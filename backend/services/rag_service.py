import chromadb
from chromadb.utils import embedding_functions
import logging
import uuid
from services.gemini_service import GeminiService, GeminiServiceError

logger = logging.getLogger(__name__)

class RAGService:
    """Uses ChromaDB for vector storage and semantic retrieval."""
    
    def __init__(self, api_key: str):
        self.client = chromadb.Client()
        class GeminiEmbeddingFunction(chromadb.EmbeddingFunction):
            def __init__(self, api_key: str):
                self.api_key = api_key
            def __call__(self, input: chromadb.Documents) -> chromadb.Embeddings:
                results = []
                for text in input:
                    try:
                        response = GeminiService.embed_content(
                            text,
                            api_key=self.api_key,
                            model_name="models/text-embedding-004"
                        )
                        results.append(response["embedding"])
                    except GeminiServiceError as e:
                        logger.error("RAG embedding failed: %s", e)
                        results.append([])
                    except Exception as e:
                        logger.exception("RAG embedding unexpected failure: %s", e)
                        results.append([])
                return results
        
        self.ef = GeminiEmbeddingFunction(api_key=api_key)
        self.collection = self.client.get_or_create_collection(name="documents", embedding_function=self.ef)
        
    def ingest_document(self, text: str):
        words = text.split()
        if not words:
            return
            
        chunks = [" ".join(words[i:i+500]) for i in range(0, len(words), 450)] 
        ids = [str(uuid.uuid4()) for _ in chunks]
        
        self.collection.add(documents=chunks, ids=ids)
        
    def search(self, query: str, top_k: int = 3) -> str:
        if self.collection.count() == 0:
            return ""
            
        # Ensure we don't request more than what's in the collection
        k = min(top_k, self.collection.count())
        
        results = self.collection.query(query_texts=[query], n_results=k)
        if results and 'documents' in results and results['documents'] and results['documents'][0]:
            return "\n\n".join(results['documents'][0])
        return ""
