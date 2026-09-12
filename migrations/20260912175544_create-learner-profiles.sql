-- One profile per learner, created on sign-up.
--
-- The gaze timings live here rather than in app config because they are the
-- accessibility setting that matters most: the dwell and confirm holds that
-- suit one person are unusable for another. ui_elements carries a per-element
-- baseline; these multipliers scale it for the individual.

CREATE TABLE public.profiles (
  user_id             UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name        TEXT,
  avatar_url          TEXT,
  -- Scales every element's dwell_ms / confirm_ms for this learner.
  dwell_multiplier    NUMERIC(3, 2) NOT NULL DEFAULT 1.00
                      CHECK (dwell_multiplier >= 0.25 AND dwell_multiplier <= 4.00),
  confirm_multiplier  NUMERIC(3, 2) NOT NULL DEFAULT 1.00
                      CHECK (confirm_multiplier >= 0.25 AND confirm_multiplier <= 4.00),
  -- Spoken explanation playback rate.
  speech_rate         NUMERIC(3, 2) NOT NULL DEFAULT 1.00
                      CHECK (speech_rate >= 0.5 AND speech_rate <= 2.0),
  -- Turn the spoken layer off for someone who prefers to read.
  audio_enabled       BOOLEAN NOT NULL DEFAULT TRUE,
  captions_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER profiles_updated_at BEFORE UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "read own profile" ON public.profiles
  FOR SELECT TO authenticated USING (user_id = (SELECT auth.uid()));
CREATE POLICY "update own profile" ON public.profiles
  FOR UPDATE TO authenticated
  USING (user_id = (SELECT auth.uid()))
  WITH CHECK (user_id = (SELECT auth.uid()));

REVOKE ALL ON public.profiles FROM anon, authenticated;
GRANT SELECT ON public.profiles TO authenticated;
-- user_id is set by the sign-up hook and must stay put.
GRANT UPDATE (display_name, avatar_url, dwell_multiplier, confirm_multiplier,
              speech_rate, audio_enabled, captions_enabled)
  ON public.profiles TO authenticated;

-- Sign-up hook
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
  INSERT INTO public.profiles (user_id, display_name, avatar_url)
  VALUES (NEW.id, NEW.profile->>'name', NEW.profile->>'avatar_url')
  ON CONFLICT (user_id) DO NOTHING;

  RETURN NEW;
END;
$$;

CREATE TRIGGER on_auth_user_created
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
