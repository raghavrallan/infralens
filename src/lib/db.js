import pg from "pg";

const SCHEMA_NAME = /^[a-z_][a-z0-9_]*$/i;

function schemaName() {
  const name = process.env.INFRALENS_SCHEMA || "public";
  if (!SCHEMA_NAME.test(name)) throw new Error("Invalid database schema name.");
  return name;
}

let pool;

function getPool() {
  if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL is not set.");
  if (!pool) {
    const connectionString = process.env.DATABASE_URL.replace(/^postgresql\+psycopg2:/, "postgresql:");
    pool = new pg.Pool({ connectionString, max: 10 });
  }
  return pool;
}

function pgSql(sql) {
  let index = 0;
  return sql.replace(/\?/g, () => `$${++index}`);
}

async function query(sql, params = []) {
  const client = await getPool().connect();
  try {
    await client.query(`SET search_path TO ${schemaName()}`);
    return await client.query(pgSql(sql), params);
  } finally {
    client.release();
  }
}

export async function one(sql, params = []) {
  const result = await query(sql, params);
  return result.rows[0] || null;
}

export async function many(sql, params = []) {
  const result = await query(sql, params);
  return result.rows;
}

export async function run(sql, params = []) {
  await query(sql, params);
}

export function isUniqueViolation(err) {
  return Boolean(err && (err.code === "23505" || /unique|duplicate key/i.test(String(err.message || ""))));
}

const CHECK_DDL = `
CREATE TABLE IF NOT EXISTS organizations (
  id VARCHAR(36) PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  slug VARCHAR(120) NOT NULL UNIQUE,
  created_by VARCHAR(36) NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS users (
  id VARCHAR(36) PRIMARY KEY,
  username VARCHAR(64) NOT NULL UNIQUE,
  email VARCHAR(255) NOT NULL DEFAULT '',
  display_name VARCHAR(120) NOT NULL DEFAULT '',
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(32) NOT NULL DEFAULT 'developer',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS org_memberships (
  id VARCHAR(36) PRIMARY KEY,
  org_id VARCHAR(36) NOT NULL,
  user_id VARCHAR(36) NOT NULL,
  org_role VARCHAR(32) NOT NULL DEFAULT 'member',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS projects (
  id VARCHAR(36) PRIMARY KEY,
  org_id VARCHAR(36) NOT NULL DEFAULT '',
  name VARCHAR(120) NOT NULL,
  slug VARCHAR(64),
  budget_usd DOUBLE PRECISION,
  repos JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS project_memberships (
  id VARCHAR(36) PRIMARY KEY,
  project_id VARCHAR(36) NOT NULL,
  user_id VARCHAR(36) NOT NULL,
  project_role VARCHAR(32) NOT NULL DEFAULT 'developer',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash VARCHAR(64) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL,
  org_id VARCHAR(36),
  expires_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS azure_connections (
  id VARCHAR(36) PRIMARY KEY,
  org_id VARCHAR(36) NOT NULL,
  name VARCHAR(120) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  client_id VARCHAR(64) NOT NULL,
  secret_cipher TEXT NOT NULL,
  status VARCHAR(32) NOT NULL,
  status_detail TEXT NOT NULL DEFAULT '',
  last_checked_at BIGINT,
  created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscriptions (
  id VARCHAR(64) PRIMARY KEY,
  org_id VARCHAR(36) NOT NULL,
  connection_id VARCHAR(36) NOT NULL,
  name VARCHAR(200) NOT NULL DEFAULT '',
  state VARCHAR(64) NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS project_subscriptions (
  project_id VARCHAR(36) NOT NULL,
  subscription_id VARCHAR(64) NOT NULL UNIQUE,
  PRIMARY KEY (project_id, subscription_id)
);
CREATE TABLE IF NOT EXISTS project_connections (
  project_id VARCHAR(36) NOT NULL,
  connection_id VARCHAR(36) NOT NULL,
  PRIMARY KEY (project_id, connection_id)
);
CREATE TABLE IF NOT EXISTS audit_log (
  id VARCHAR(36) PRIMARY KEY,
  org_id VARCHAR(36),
  project_id VARCHAR(36),
  user_id VARCHAR(36),
  action VARCHAR(64) NOT NULL,
  detail TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS estate_snapshots (
  org_id VARCHAR(36) NOT NULL,
  project_id VARCHAR(36) NOT NULL,
  range_id VARCHAR(16) NOT NULL,
  payload JSONB NOT NULL,
  synced_at BIGINT NOT NULL,
  PRIMARY KEY (org_id, project_id, range_id)
);
CREATE TABLE IF NOT EXISTS estate_schedules (
  org_id VARCHAR(36) NOT NULL,
  project_id VARCHAR(36) NOT NULL,
  cadence VARCHAR(16) NOT NULL,
  updated_at BIGINT NOT NULL,
  PRIMARY KEY (org_id, project_id)
);
CREATE TABLE IF NOT EXISTS estate_syncs (
  org_id VARCHAR(36) NOT NULL,
  project_id VARCHAR(36) NOT NULL,
  range_id VARCHAR(16) NOT NULL,
  started_at BIGINT NOT NULL,
  PRIMARY KEY (org_id, project_id, range_id)
);
CREATE TABLE IF NOT EXISTS sandbox_calls (
  id VARCHAR(36) PRIMARY KEY,
  org_id VARCHAR(36),
  project_id VARCHAR(36),
  user_id VARCHAR(36),
  connection_id VARCHAR(36) NOT NULL,
  command VARCHAR(32) NOT NULL,
  method VARCHAR(8) NOT NULL DEFAULT '',
  route TEXT NOT NULL,
  caller VARCHAR(120) NOT NULL DEFAULT '',
  status VARCHAR(16) NOT NULL,
  duration_ms INTEGER NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS sandbox_calls_connection_idx ON sandbox_calls (connection_id, created_at DESC);
`;

export async function ensureConsoleSchema() {
  const name = schemaName();
  const client = await getPool().connect();
  try {
    if (name !== "public") await client.query(`CREATE SCHEMA IF NOT EXISTS ${name}`);
    await client.query(`SET search_path TO ${name}`);
    await client.query(CHECK_DDL);
  } finally {
    client.release();
  }
}

export async function dropConsoleSchema() {
  const name = schemaName();
  if (name === "public") return;
  await query(`DROP SCHEMA IF EXISTS ${name} CASCADE`);
}

export async function closeDb() {
  if (pool) await pool.end();
  pool = null;
}
