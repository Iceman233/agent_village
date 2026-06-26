-- Conversation history, partitioned by trust context.
-- Owner rows and stranger rows are never queried together — see
-- backend/app/context_owner.py vs backend/app/context_public.py.
CREATE TABLE IF NOT EXISTS living_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES living_agents(id) ON DELETE CASCADE,
    sender_type TEXT NOT NULL CHECK (sender_type IN ('owner', 'stranger')),
    sender_ref TEXT,
    role TEXT NOT NULL CHECK (role IN ('user', 'agent')),
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_living_messages_agent ON living_messages(agent_id, sender_type, created_at DESC);

ALTER TABLE living_messages ENABLE ROW LEVEL SECURITY;

-- No anon policy: conversation history (including owner content) is only
-- ever touched by the backend's service role key, never the frontend's anon key.
CREATE POLICY "service_all_messages" ON living_messages FOR ALL USING (auth.role() = 'service_role');
