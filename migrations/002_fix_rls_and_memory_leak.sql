-- The reference schema (setup-database.sql) has two trust-boundary bugs
-- that bypass the backend's context-builder separation entirely, since
-- the frontend reads/writes Supabase directly with the public anon key:
--
-- 1. activity_feed UNIONs in living_memory content as 'memory_added'
--    events, broadcasting private owner facts (e.g. "wife's birthday is
--    March 15, she loves orchids") on the public Updates feed.
-- 2. Every "service_all_*" policy uses USING(true) WITH CHECK(true) with
--    no role restriction, so it applies to the anon role too (confirmed:
--    anon could INSERT/DELETE living_memory rows directly, not just read
--    them). Only living_activity_events was correctly scoped to
--    service_role in the original schema; this brings the rest in line.

-- 1. Drop the memory_added branch from the public feed view.
CREATE OR REPLACE VIEW activity_feed AS
    SELECT id, 'skill_added'::text as type, agent_id, description as text,
           NULL::text as proof_url, NULL::text as emoji, created_at
    FROM living_skills
    UNION ALL
    SELECT id, 'learning_log'::text as type, agent_id, text, proof_url, emoji, created_at
    FROM living_log
    UNION ALL
    SELECT id, 'diary_entry'::text as type, agent_id,
           LEFT(text, 60) || CASE WHEN LENGTH(text) > 60 THEN '...' ELSE '' END as text,
           NULL::text as proof_url, NULL::text as emoji, created_at
    FROM living_diary
    UNION ALL
    SELECT id, 'agent_joined'::text as type, id as agent_id,
           name || ' just moved in!' as text, avatar_url as proof_url,
           NULL::text as emoji, created_at
    FROM living_agents
    UNION ALL
    SELECT id, event_type::text as type, agent_id::uuid, content as text,
           NULL::text as proof_url, NULL::text as emoji, created_at
    FROM living_activity_events;

-- 2. living_memory: anon gets no access at all, not even SELECT.
DROP POLICY IF EXISTS "anon_read_memory" ON living_memory;
DROP POLICY IF EXISTS "service_all_memory" ON living_memory;
CREATE POLICY "service_all_memory" ON living_memory
    FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');

-- 3. Everything else: anon keeps its intentional read-only access
--    (already granted by anon_read_* policies), writes are service-role only.
DROP POLICY IF EXISTS "service_all_agents" ON living_agents;
CREATE POLICY "service_all_agents" ON living_agents
    FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "service_all_skills" ON living_skills;
CREATE POLICY "service_all_skills" ON living_skills
    FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "service_all_diary" ON living_diary;
CREATE POLICY "service_all_diary" ON living_diary
    FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "service_all_log" ON living_log;
CREATE POLICY "service_all_log" ON living_log
    FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "service_all_announcements" ON announcements;
CREATE POLICY "service_all_announcements" ON announcements
    FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
