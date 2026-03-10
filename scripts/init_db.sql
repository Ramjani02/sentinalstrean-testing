-- SentinelStream - Database Initialization
-- Creates extensions and grants required privileges.
-- This script runs once when the PostgreSQL container first starts.

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pgcrypto for additional cryptographic functions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Grant all privileges to the sentinel user
GRANT ALL PRIVILEGES ON DATABASE sentinelstream TO sentinel;

-- Log successful initialization
DO $$ BEGIN
    RAISE NOTICE 'SentinelStream database initialized successfully';
END $$;
