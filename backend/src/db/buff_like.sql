CREATE TABLE IF NOT EXISTS buff_like_jobs (
  order_id uuid PRIMARY KEY REFERENCES orders(id),
  target_name text NOT NULL,
  requested integer NOT NULL CHECK (requested BETWEEN 1 AND 1000000),
  done integer NOT NULL DEFAULT 0 CHECK (done >= 0 AND done <= requested),
  state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','claimed','running','needs_review','completed')),
  device_id uuid,
  claim_token uuid UNIQUE,
  admin_id uuid REFERENCES users(id),
  engine_order_id text,
  engine_stopped boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS buff_like_queue_idx ON buff_like_jobs(state,created_at);
