from .base import EmbeddingStrategy  # Adjust import based on your file layout

class SentenceTransformerEmbeddingStrategy(EmbeddingStrategy):
    def __init__(
        self, 
        model_name: str = "all-MiniLM-L6-v2", 
        batch_size: int = 32, 
        batch_timeout: float = 1.5
    ):
        """
        Concrete embedding strategy utilizing the local sentence-transformers library.
        
        Args:
            model_name: HuggingFace model identifier. Defaults to 'all-MiniLM-L6-v2' ( ~80MB ).
            batch_size: The target micro-batch size for the consumer queue.
            batch_timeout: The maximum time windows to wait before flushing an incomplete batch.
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "Could not import 'sentence_transformers'. "
                "Please install it with 'pip install sentence-transformers'."
            )

        super().__init__(batch_size=batch_size, batch_timeout=batch_timeout)
        self.model_name = model_name
        
        # Loads directly from disk cache if downloaded previously (~/.cache/huggingface)
        self.model = SentenceTransformer(model_name)

    @property
    def dimensions(self) -> int:
        """
        Dynamically inspects the active model to report its vector footprint.
        Required for structural database initialization tasks (e.g., float[384]).
        """
        return self.model.get_sentence_embedding_dimension() or 384

    def embed_batch(self, descriptions: list[str]) -> list[list[float]]:
        """
        Synchronous CPU-bound vector calculation for a micro-batch of descriptions.
        Executed strictly out-of-thread by the parent EmbeddingClient.
        
        Returns a list of native float lists, ensuring clean compliance with 
        Tostr's subsequent downstream JSON flattening phase.
        """
        if not descriptions:
            return []

        # PyTorch crunches the entire list concurrently at the C++ level
        embeddings_ndarray = self.model.encode(
            descriptions, 
            convert_to_numpy=True, 
            show_progress_bar=False
        )
        
        # Convert the dense numpy matrix to standard serialized float arrays
        return embeddings_ndarray.tolist()

    def embed_query(self, query: str) -> list[float]:
        """
        Helper method used exclusively during interactive top-k vector searches.
        """
        return self.model.encode(query, convert_to_numpy=True).tolist()