-- Central email allowlist for ALL public HanaV Streamlit apps.
-- Run this in the EXISTING HanaV-Finder Supabase SQL editor.
-- It creates a NEW table only and does not change any existing ETF/corporate tables.
--
-- Approved users authenticate with Supabase Auth OTP (custom SMTP required
-- for recipients who are not Supabase project team members).
-- Use Authentication > Users to precreate/invite allowed email accounts.
--
-- Security: NO public/anonymous table read or write. Users can only SELECT
-- their OWN verified email's entries via RLS. Admin updates via SQL editor.
CREATE TABLE IF NOT EXISTS public.hanav_app_access (
    email text NOT NULL,
    app_code text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (email, app_code),
    CONSTRAINT hanav_email_valid CHECK (
        email = lower(btrim(email))
        AND length(email) BETWEEN 5 AND 254
        AND position('@' in email) > 1
    ),
    CONSTRAINT hanav_app_scope CHECK (
        app_code IN (
            'all',
            'stock-analyzer',
            'hanav-trading',
            'corporate-finder',
            'pension-tax',
            'private-portfolio'
        )
    )
);

ALTER TABLE public.hanav_app_access ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.hanav_app_access FROM anon, authenticated;
GRANT SELECT ON TABLE public.hanav_app_access TO authenticated;

DROP POLICY IF EXISTS hanav_user_reads_own_approval ON public.hanav_app_access;
CREATE POLICY hanav_user_reads_own_approval
ON public.hanav_app_access
FOR SELECT TO authenticated
USING (
    lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
);

COMMENT ON TABLE public.hanav_app_access IS
    'HanaV owner-managed app access grants. No end-user insert/update/delete.';

NOTIFY pgrst, 'reload schema';

-- EXAMPLE ONLY, do not run without replacing the email address:
--
-- 1) Allow an email to use every public HanaV app:
-- INSERT INTO public.hanav_app_access(email, app_code, enabled)
-- VALUES ('approved@example.com', 'all', true)
-- ON CONFLICT (email, app_code)
-- DO UPDATE SET enabled=excluded.enabled, updated_at=now();
--
-- 2) Allow a specific app only:
-- INSERT INTO public.hanav_app_access(email, app_code, enabled)
-- VALUES ('colleague@example.com', 'stock-analyzer', true)
-- ON CONFLICT (email, app_code)
-- DO UPDATE SET enabled=excluded.enabled, updated_at=now();
--
-- 3) Deny one app despite an 'all' grant (specific denial wins):
-- INSERT INTO public.hanav_app_access(email, app_code, enabled)
-- VALUES ('approved@example.com', 'private-portfolio', false)
-- ON CONFLICT (email, app_code)
-- DO UPDATE SET enabled=false, updated_at=now();
--
-- 4) Revoke all access for one email:
-- DELETE FROM public.hanav_app_access WHERE email='approved@example.com';
--
-- IMPORTANT: A verified auth account and an active grant are BOTH required.
-- No user can edit this table by using an app's public anon key.
