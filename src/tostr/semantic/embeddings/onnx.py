from __future__ import annotations
import os
import sys
from pathlib import Path
from importlib import resources
from loguru import logger
import numpy as np
from .base import EmbeddingStrategy

class OnnxEmbeddingStrategy(EmbeddingStrategy):
    def __init__(self, batch_size: int = 32, batch_timeout: float = 1.5):
        super().__init__(batch_size=batch_size, batch_timeout=batch_timeout)
        
        # 1. Target relative subdirectory signature
        target_subpath = "resources/models/all-MiniLM-L6-v2"
        model_dir = None

        # 2. Attempt: Packaged/Distributed Resolution
        try:
            packaged_path = resources.files("tostr").joinpath(target_subpath)
            if packaged_path.joinpath("model.onnx").exists():
                model_dir = Path(str(packaged_path))
                logger.debug(f"Resolved bundled model assets via importlib: {model_dir}")
        except Exception:
            pass  # Suppress and fallback gracefully

        # 3. Attempt: Fallback for Editable Installs & Testing Environment
        if model_dir is None:
            # __file__ is inside src/tostr/semantic/ or similar submodule path.
            # Traverse upwards to find the package directory root containing /resources/
            current_file_dir = Path(__file__).resolve().parent
            
            # Walk up until you find the 'tostr' parent directory that holds 'resources'
            for parent in [current_file_dir] + list(current_file_dir.parents):
                possible_path = parent / target_subpath
                if possible_path.joinpath("model.onnx").exists():
                    model_dir = possible_path
                    logger.debug(f"Resolved editable model assets via repository layout fallback: {model_dir}")
                    break

        # 4. Critical Failure State Catch
        if model_dir is None or not model_dir.exists():
            raise FileNotFoundError(
                f"ONNX Model Assets could not be located in packaged context or fallback tree.\n"
                f"Ensure your binary weights are located at: /Tostr/resources/models/all-MiniLM-L6-v2/"
            )

        self.onnx_path = str(model_dir / "model.onnx")
        self.vocab_path = str(model_dir / "tokenizer.json")

        # 5. Fast, lightweight engine instantiation
        import onnxruntime as ort
        from tokenizers import Tokenizer
        
        self.tokenizer = Tokenizer.from_file(self.vocab_path)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        
        self.session = ort.InferenceSession(self.onnx_path, providers=["CPUExecutionProvider"])

    @property
    def dimensions(self) -> int:
        return 384

    def _ensure_assets_present(self):
        """Verifies assets are on local drive; fetches from source if empty."""
        if os.path.exists(self.onnx_path) and os.path.exists(self.vocab_path):
            return
            
        os.makedirs(self.model_dir, exist_ok=True)
        logger.info("First-time run: Fetching optimized embedding assets...")
        
        # Replace these URLs with your hosted GitHub release artifacts or CDN paths
        base_url = "https://raw.githubusercontent.com/your-username/tostr-assets/main/all-MiniLM-L6-v2"
        
        try:
            urllib.request.urlretrieve(f"{base_url}/model.onnx", self.onnx_path)
            urllib.request.urlretrieve(f"{base_url}/tokenizer.json", self.vocab_path)
            logger.info("Embedding assets cached successfully.")
        except Exception as e:
            raise RuntimeError(f"Failed to fetch local model assets: {e}")

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