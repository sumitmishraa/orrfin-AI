-- Apply only to the dedicated VendorMind Supabase project, after pilot tables exist.
-- The browser uses the FastAPI API, not Supabase's Data API for pilot tables.
-- Revoke Data API access and add organization-scoped RLS as defense in depth.
DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'pilot_organizations', 'pilot_members', 'pilot_vendors', 'pilot_requests',
    'pilot_invitations', 'pilot_quotes', 'pilot_orders', 'pilot_receipts',
    'pilot_invoices', 'pilot_audit', 'pilot_memory_events',
    'suppliers', 'events', 'decisions'
  ] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated', table_name);
  END LOOP;
END $$;

DROP POLICY IF EXISTS member_self_read ON public.pilot_members;
CREATE POLICY member_self_read ON public.pilot_members FOR SELECT TO authenticated
  USING (user_id = (select auth.uid())::text);
DROP POLICY IF EXISTS organization_member_read ON public.pilot_organizations;
CREATE POLICY organization_member_read ON public.pilot_organizations FOR SELECT TO authenticated
  USING (EXISTS (SELECT 1 FROM public.pilot_members m WHERE m.org_id = pilot_organizations.id AND m.user_id = (select auth.uid())::text));

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'pilot_vendors', 'pilot_requests', 'pilot_invitations', 'pilot_quotes',
    'pilot_orders', 'pilot_receipts', 'pilot_invoices', 'pilot_audit', 'pilot_memory_events'
  ] LOOP
    EXECUTE format('DROP POLICY IF EXISTS organization_member_read ON public.%I', table_name);
    EXECUTE format(
      'CREATE POLICY organization_member_read ON public.%I FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.pilot_members m WHERE m.org_id = %I.org_id AND m.user_id = (select auth.uid())::text))',
      table_name, table_name
    );
  END LOOP;
END $$;
