"""
NCI Engine - Automated RAG Pipeline

Complete modular RAG system with:
- Data Ingestion (crawl → clean → index)
- Inference (query → retrieve → generate)
- Evaluation (test → metrics → feedback)
"""

from .inference import InferencePipeline
from .ingestion import DataIngestionPipeline
from .orchestrator import NCIPipeline

__all__ = ["NCIPipeline", "DataIngestionPipeline", "InferencePipeline"]
