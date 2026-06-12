from __future__ import annotations
import urllib.request
from pathlib import Path
from loguru import logger
import numpy as np
from .base import EmbeddingStrategy

_CACHE_DIR = Path.home() / ".cache" / "tostr" / "models" / "all-MiniLM-L6-v2"
_HF_BASE = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main"
_ASSETS = {
    "model.onnx": f"{_HF_BASE}/onnx/model.onnx",
    "tokenizer.json": f"{_HF_BASE}/tokenizer.json",
}

class OnnxEmbeddingStrategy(EmbeddingStrategy):
    def __init__(self, batch_size: int = 32, batch_timeout: float = 1.5):
        super().__init__(batch_size=batch_size, batch_timeout=batch_timeout)

        self.model_dir = _CACHE_DIR
        self.onnx_path = str(self.model_dir / "model.onnx")
        self.vocab_path = str(self.model_dir / "tokenizer.json")

        self._ensure_assets_present()

        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_file(self.vocab_path)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self.session = ort.InferenceSession(self.onnx_path, providers=["CPUExecutionProvider"])

    @property
    def dimensions(self) -> int:
        return 384

    def _ensure_assets_present(self):
        if all(Path(p).exists() for p in (self.onnx_path, self.vocab_path)):
            return

        self.model_dir.mkdir(parents=True, exist_ok=True)
        logger.info("First-time setup: downloading embedding model from Hugging Face Hub (~86 MB)...")

        for filename, url in _ASSETS.items():
            dest = self.model_dir / filename
            if dest.exists():
                continue
            logger.info(f"Downloading {filename}...")
            try:
                urllib.request.urlretrieve(url, dest)
            except Exception as e:
                dest.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Failed to download {filename} from Hugging Face Hub.\n"
                    f"URL: {url}\nError: {e}"
                ) from e

        logger.info("Embedding model cached to ~/.cache/tostr/")

    def _execute_onnx(self, texts: list[str]) -> list[list[float]]:
        """Executes compiled math graph using tokenizers and ONNX runtime layers."""
        # Clean out empty calls early
        if not texts:
            return []
            
        # Fast Rust Tokenization (Runs in <1ms)
        encoded = self.tokenizer.encode_batch(texts)
        
        # Convert input mappings to raw NumPy containers
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        
        # MiniLM expects a token type index layer (usually zeros)
        token_type_ids = np.zeros_like(input_ids, dtype=np.int64)
        
        # Prepare execution payload mapping to ONNX variable expectations
        ort_inputs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids
        }
        
        # Execute compiled forward-pass matrices
        ort_outputs = self.session.run(None, ort_inputs)
        
        # Output indices depend on configuration (Typically index 0 is token embeddings)
        token_embeddings = ort_outputs[0] 
        
        # Perform Mean Pooling over the attention mask to compute structural sequence tokens
        input_mask_expanded = np.expand_dims(attention_mask, axis=-1).astype(float)
        sum_embeddings = np.sum(token_embeddings * input_mask_expanded, axis=1)
        sum_mask = np.clip(input_mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
        
        # Calculate centroids and normalize vector profiles to Euclidean unit length
        pooled = sum_embeddings / sum_mask
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized_embeddings = pooled / np.clip(norms, a_min=1e-9, a_max=None)
        
        return normalized_embeddings.tolist()

    def embed_batch(self, descriptions: list[str]) -> list[list[float]]:
        return self._execute_onnx(descriptions)

    def embed_query(self, query: str) -> list[float]:
        return self._execute_onnx([query])[0]