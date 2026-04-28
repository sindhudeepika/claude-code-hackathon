-- Contoso Financial reporting database schema
-- Target: Azure Database for PostgreSQL Flexible Server, UK South
-- PII fields are tagged in column comments

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pgaudit";

-- Customers
CREATE TABLE customers (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  first_name    VARCHAR(100) NOT NULL,
  last_name     VARCHAR(100) NOT NULL,
  email         VARCHAR(255) NOT NULL UNIQUE, -- PII
  phone         VARCHAR(20),                  -- PII
  uk_postcode   VARCHAR(10),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_customers_email ON customers (email);
CREATE INDEX idx_customers_created_at ON customers (created_at DESC);

-- Accounts
CREATE TABLE accounts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id     UUID NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
  account_number  VARCHAR(20) NOT NULL UNIQUE, -- PII
  sort_code       VARCHAR(10) NOT NULL,         -- PII
  account_type    VARCHAR(50) NOT NULL CHECK (account_type IN ('current', 'savings', 'isa', 'mortgage')),
  balance         NUMERIC(15,2) NOT NULL DEFAULT 0.00,
  currency        CHAR(3) NOT NULL DEFAULT 'GBP',
  opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_accounts_customer_id ON accounts (customer_id);

-- Transactions
CREATE TABLE transactions (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id       UUID NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  amount           NUMERIC(15,2) NOT NULL,
  description      VARCHAR(500),
  transaction_date DATE NOT NULL,
  status           VARCHAR(50) NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'cleared', 'reconciled', 'disputed', 'reversed')),
  external_ref     VARCHAR(100) UNIQUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_transactions_account_id ON transactions (account_id);
CREATE INDEX idx_transactions_date ON transactions (transaction_date DESC);
CREATE INDEX idx_transactions_external_ref ON transactions (external_ref);
CREATE INDEX idx_transactions_status ON transactions (status);

-- Reconciliation Reports (written by batch job)
CREATE TABLE reconciliation_reports (
  id               SERIAL PRIMARY KEY,
  report_date      DATE NOT NULL UNIQUE,
  status           VARCHAR(50) NOT NULL CHECK (status IN ('completed', 'failed', 'partial')),
  total_processed  INTEGER NOT NULL DEFAULT 0,
  total_matched    INTEGER NOT NULL DEFAULT 0,
  total_unmatched  INTEGER NOT NULL DEFAULT 0,
  total_invalid    INTEGER NOT NULL DEFAULT 0,
  unmatched_refs   TEXT[],
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_reconciliation_date ON reconciliation_reports (report_date DESC);

-- Updated_at trigger
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER customers_updated_at
  BEFORE UPDATE ON customers
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
