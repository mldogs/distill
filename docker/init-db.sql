-- Create additional databases for services
-- This script runs on first PostgreSQL initialization

-- pgvector extension for semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- Umami analytics database
CREATE DATABASE umami;
GRANT ALL PRIVILEGES ON DATABASE umami TO postgres;
