-- tower_tooling: pinned Figma fidelity references (Addendum 2.5).
-- Images live in the private Blob store; this database stores provenance and integrity only.

CREATE TABLE fidelity_reference_set (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  figma_file_key text NOT NULL CHECK (figma_file_key ~ '^[A-Za-z0-9]+$'),
  figma_version_id text NOT NULL CHECK (figma_version_id ~ '^[0-9]+$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  is_active boolean NOT NULL DEFAULT false,
  note text,
  UNIQUE (figma_file_key, figma_version_id)
);

-- Exactly one active set: at most one row may hold is_active = true.
CREATE UNIQUE INDEX fidelity_reference_set_one_active ON fidelity_reference_set (is_active) WHERE is_active;

CREATE TABLE fidelity_reference_image (
  set_id bigint NOT NULL REFERENCES fidelity_reference_set (id) ON DELETE CASCADE,
  node_id text NOT NULL,
  screen_key text NOT NULL CHECK (screen_key ~ '^[a-z0-9-]+@[12]x$'),
  viewport text NOT NULL CHECK (viewport ~ '^[0-9]+@[12]x$'),
  blob_url text NOT NULL CHECK (blob_url ~ '^(https|file)://'),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  width integer NOT NULL CHECK (width > 0),
  height integer NOT NULL CHECK (height > 0),
  PRIMARY KEY (set_id, screen_key),
  UNIQUE (set_id, node_id, viewport)
);

-- Bounding boxes of every node under each exported root, relative to that root (the frozen geometry.json).
CREATE TABLE fidelity_reference_node (
  set_id bigint NOT NULL REFERENCES fidelity_reference_set (id) ON DELETE CASCADE,
  root_node_id text NOT NULL,
  node_id text NOT NULL,
  name text NOT NULL,
  x double precision NOT NULL,
  y double precision NOT NULL,
  width double precision NOT NULL CHECK (width >= 0),
  height double precision NOT NULL CHECK (height >= 0),
  PRIMARY KEY (set_id, root_node_id, node_id)
);
