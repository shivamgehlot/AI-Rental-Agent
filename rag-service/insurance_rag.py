"""Insurance RAG service for document ingestion and Q&A."""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from typing import Any

import chromadb
from fastapi import FastAPI, File, HTTPException, UploadFile
from langchain.chains import RetrievalQA
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.llms import Ollama
from langchain_community.vectorstores import Chroma
from minio import Minio
from pydantic_settings import BaseSettings, SettingsConfigDict


class RagSettings(BaseSettings):
    """Configuration for RAG dependencies."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    EMBEDDING_MODEL: str = "nomic-embed-text"
    LLM_MODEL: str = "mistral"
    CHROMA_HOST: str = "chroma"
    CHROMA_PORT: int = 8000
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_SECURE: bool = False
    MINIO_BUCKET: str = "rideswift-docs"


@lru_cache(maxsize=1)
def get_settings() -> RagSettings:
    """Return cached settings."""
    return RagSettings()


@lru_cache(maxsize=1)
def get_embeddings() -> OllamaEmbeddings:
    """Create embeddings provider."""
    settings = get_settings()
    return OllamaEmbeddings(model=settings.EMBEDDING_MODEL, base_url=settings.OLLAMA_BASE_URL)


@lru_cache(maxsize=1)
def get_llm() -> Ollama:
    """Create LLM client."""
    settings = get_settings()
    return Ollama(model=settings.LLM_MODEL, base_url=settings.OLLAMA_BASE_URL)


@lru_cache(maxsize=1)
def get_minio_client() -> Minio:
    """Create MinIO client."""
    settings = get_settings()
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def _ensure_bucket() -> None:
    """Ensure target MinIO bucket exists."""
    settings = get_settings()
    minio_client = get_minio_client()
    if not minio_client.bucket_exists(settings.MINIO_BUCKET):
        minio_client.make_bucket(settings.MINIO_BUCKET)


def get_chroma_client() -> chromadb.HttpClient:
    """Create Chroma client lazily."""
    settings = get_settings()
    return chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)


def ingest_insurance_pdf(customer_id: str, pdf_path: str) -> str:
    """Upload PDF to MinIO and embed into Chroma."""
    settings = get_settings()
    _ensure_bucket()
    minio_client = get_minio_client()
    chroma_client = get_chroma_client()

    object_name = f"insurance/{customer_id}/{os.path.basename(pdf_path)}"
    minio_client.fput_object(settings.MINIO_BUCKET, object_name, pdf_path)

    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_documents(docs)
    for chunk in chunks:
        chunk.metadata["customer_id"] = customer_id

    vectorstore = Chroma(
        client=chroma_client,
        collection_name=f"insurance_{customer_id}",
        embedding_function=get_embeddings(),
    )
    vectorstore.add_documents(chunks)
    return f"Ingested {len(chunks)} chunks for customer {customer_id}"


def query_insurance(customer_id: str, question: str) -> dict[str, Any]:
    """Answer insurance questions using customer-specific collection."""
    vectorstore = Chroma(
        client=get_chroma_client(),
        collection_name=f"insurance_{customer_id}",
        embedding_function=get_embeddings(),
    )
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
    qa_chain = RetrievalQA.from_chain_type(
        llm=get_llm(),
        retriever=retriever,
        chain_type="stuff",
        return_source_documents=True,
    )
    result = qa_chain.invoke({"query": question})
    return {
        "answer": result["result"],
        "sources": [doc.page_content[:200] for doc in result["source_documents"]],
    }


app = FastAPI(title="RideSwift Insurance RAG")


@app.post("/rag/upload/{customer_id}")
async def upload_insurance(customer_id: str, file: UploadFile = File(...)) -> dict[str, str]:
    """Upload customer insurance PDF and ingest it into vector store."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
        tmp_file.write(await file.read())
        temp_path = tmp_file.name
    try:
        message = ingest_insurance_pdf(customer_id, temp_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return {"message": message}


@app.post("/rag/query/{customer_id}")
async def query_insurance_endpoint(customer_id: str, body: dict[str, str]) -> dict[str, Any]:
    """Query customer insurance coverage from ingested documents."""
    question = body.get("question")
    if not question:
        raise HTTPException(status_code=422, detail="question is required")
    return query_insurance(customer_id, question)
