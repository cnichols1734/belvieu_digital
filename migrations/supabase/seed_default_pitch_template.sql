-- Seed: default Site Built Preview pitch template
-- Apply to Supabase (PostgreSQL) production database.
-- Idempotent: does nothing if a template with this exact name already exists.

INSERT INTO pitch_templates (id, name, body, category, is_active)
SELECT
    gen_random_uuid()::text,
    'Site Built Preview — $29/mo',
    E'Hey! I came across your business and noticed you don''t have a website, so I built you a website preview so you could see what it could look like.\n\nIt’s fully customizable, and if you want to use it, it’s just $29/month with no contracts or upfront build fee. Free Domain included or we can use the one you own.  {{demo_url}} If you’re interested, shoot me a message and I can get everything set up for you.',
    'initial',
    TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM pitch_templates
    WHERE name = 'Site Built Preview — $29/mo'
);
