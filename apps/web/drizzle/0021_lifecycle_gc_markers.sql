ALTER TABLE media_objects ADD COLUMN IF NOT EXISTS orphaned_at timestamptz;
CREATE INDEX IF NOT EXISTS media_objects_orphaned_candidates ON media_objects (orphaned_at) WHERE orphaned_at IS NOT NULL;
