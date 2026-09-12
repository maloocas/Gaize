-- Gaize content catalog: the apps a learner practices in, the UI elements Gaize
-- can explain out loud, and the goal / scenario / quiz material layered on top.
--
-- Everything here is authored by the Gaize team through the CLI or admin key.
-- Runtime roles (anon, authenticated) get read-only access, and the tables that
-- hold answer keys (scenario_steps, quiz_options.is_correct, question
-- explanations) are kept out of reach entirely and exposed through narrow
-- projections instead.

-- ---------------------------------------------------------------------------
-- Apps and their explainable UI elements
-- ---------------------------------------------------------------------------

CREATE TABLE public.apps (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  description TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE public.ui_elements (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  app_id      UUID NOT NULL REFERENCES public.apps(id) ON DELETE CASCADE,
  -- Stable key the app reports with each gaze event, e.g. 'export-button'.
  element_key TEXT NOT NULL,
  label       TEXT NOT NULL,
  -- What Gaize says out loud when the gaze dwells here.
  explanation TEXT NOT NULL,
  -- Pre-rendered audio for the explanation, stored in the gaize-audio bucket.
  audio_bucket TEXT,
  audio_key    TEXT,
  audio_url    TEXT,
  -- Gaze timing: dwell long enough to hear the explanation, hold longer to act.
  dwell_ms     INTEGER NOT NULL DEFAULT 600  CHECK (dwell_ms > 0),
  confirm_ms   INTEGER NOT NULL DEFAULT 1200 CHECK (confirm_ms > 0),
  sort_order   INTEGER NOT NULL DEFAULT 0,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (app_id, element_key),
  CHECK (confirm_ms >= dwell_ms)
);

CREATE INDEX idx_ui_elements_app_id ON public.ui_elements(app_id);

-- ---------------------------------------------------------------------------
-- Goals: "learn how to export a photo", broken into ordered steps
-- ---------------------------------------------------------------------------

CREATE TABLE public.goals (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  app_id      UUID NOT NULL REFERENCES public.apps(id) ON DELETE CASCADE,
  slug        TEXT NOT NULL,
  title       TEXT NOT NULL,
  description TEXT,
  difficulty  TEXT NOT NULL DEFAULT 'beginner'
              CHECK (difficulty IN ('beginner', 'intermediate', 'advanced')),
  sort_order  INTEGER NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (app_id, slug)
);

CREATE INDEX idx_goals_app_id ON public.goals(app_id);

CREATE TABLE public.goal_steps (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  goal_id     UUID NOT NULL REFERENCES public.goals(id) ON DELETE CASCADE,
  step_number INTEGER NOT NULL CHECK (step_number > 0),
  -- Told to the learner up front: goals teach, they do not test.
  instruction TEXT NOT NULL,
  element_id  UUID REFERENCES public.ui_elements(id) ON DELETE SET NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (goal_id, step_number)
);

CREATE INDEX idx_goal_steps_goal_id ON public.goal_steps(goal_id);

-- ---------------------------------------------------------------------------
-- Scenarios: a task the learner performs in the app, verified live.
-- scenario_steps is the answer key and never leaves the server.
-- ---------------------------------------------------------------------------

CREATE TABLE public.scenarios (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  app_id             UUID NOT NULL REFERENCES public.apps(id) ON DELETE CASCADE,
  goal_id            UUID REFERENCES public.goals(id) ON DELETE SET NULL,
  slug               TEXT NOT NULL,
  title              TEXT NOT NULL,
  -- The task handed to the learner, e.g. "Export this photo as a PNG."
  prompt             TEXT NOT NULL,
  time_limit_seconds INTEGER CHECK (time_limit_seconds IS NULL OR time_limit_seconds > 0),
  -- When true the steps must be performed in order to count.
  strict_order       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (app_id, slug)
);

CREATE INDEX idx_scenarios_app_id ON public.scenarios(app_id);
CREATE INDEX idx_scenarios_goal_id ON public.scenarios(goal_id);

CREATE TABLE public.scenario_steps (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scenario_id     UUID NOT NULL REFERENCES public.scenarios(id) ON DELETE CASCADE,
  step_number     INTEGER NOT NULL CHECK (step_number > 0),
  element_id      UUID NOT NULL REFERENCES public.ui_elements(id) ON DELETE CASCADE,
  -- Which gaze event on that element satisfies the step.
  expected_action TEXT NOT NULL DEFAULT 'confirm'
                  CHECK (expected_action IN ('hover', 'confirm', 'action')),
  -- Surfaced only after the learner is stuck or the scenario ends.
  hint            TEXT,
  required        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (scenario_id, step_number)
);

CREATE INDEX idx_scenario_steps_scenario_id ON public.scenario_steps(scenario_id);
CREATE INDEX idx_scenario_steps_element_id ON public.scenario_steps(element_id);

-- ---------------------------------------------------------------------------
-- Quizzes: multiple choice, graded server-side, feedback at the end
-- ---------------------------------------------------------------------------

CREATE TABLE public.quizzes (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  goal_id        UUID NOT NULL REFERENCES public.goals(id) ON DELETE CASCADE,
  title          TEXT NOT NULL,
  pass_threshold NUMERIC(4, 3) NOT NULL DEFAULT 0.7
                 CHECK (pass_threshold > 0 AND pass_threshold <= 1),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_quizzes_goal_id ON public.quizzes(goal_id);

CREATE TABLE public.quiz_questions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  quiz_id         UUID NOT NULL REFERENCES public.quizzes(id) ON DELETE CASCADE,
  question_number INTEGER NOT NULL CHECK (question_number > 0),
  prompt          TEXT NOT NULL,
  -- Why the right answer is right. Withheld until the attempt is submitted.
  explanation     TEXT,
  element_id      UUID REFERENCES public.ui_elements(id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (quiz_id, question_number)
);

CREATE INDEX idx_quiz_questions_quiz_id ON public.quiz_questions(quiz_id);

CREATE TABLE public.quiz_options (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  question_id   UUID NOT NULL REFERENCES public.quiz_questions(id) ON DELETE CASCADE,
  option_number INTEGER NOT NULL CHECK (option_number > 0),
  text          TEXT NOT NULL,
  is_correct    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (question_id, option_number)
);

CREATE INDEX idx_quiz_options_question_id ON public.quiz_options(question_id);

-- ---------------------------------------------------------------------------
-- Answer-key-free projections the client is allowed to read
-- ---------------------------------------------------------------------------

-- Owned by project_admin, so these read past the locked-down base tables and
-- hand out only the columns a learner may see mid-quiz.
CREATE VIEW public.quiz_questions_public AS
  SELECT id, quiz_id, question_number, prompt, element_id
  FROM public.quiz_questions;

CREATE VIEW public.quiz_options_public AS
  SELECT id, question_id, option_number, text
  FROM public.quiz_options;

-- Lets the website show "this scenario has 4 steps" without leaking which ones.
CREATE VIEW public.scenario_step_counts AS
  SELECT scenario_id,
         COUNT(*)::INTEGER                                      AS step_count,
         COUNT(*) FILTER (WHERE required)::INTEGER              AS required_step_count
  FROM public.scenario_steps
  GROUP BY scenario_id;

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------

CREATE TRIGGER apps_updated_at BEFORE UPDATE ON public.apps
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER ui_elements_updated_at BEFORE UPDATE ON public.ui_elements
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER goals_updated_at BEFORE UPDATE ON public.goals
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER goal_steps_updated_at BEFORE UPDATE ON public.goal_steps
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER scenarios_updated_at BEFORE UPDATE ON public.scenarios
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER scenario_steps_updated_at BEFORE UPDATE ON public.scenario_steps
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER quizzes_updated_at BEFORE UPDATE ON public.quizzes
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER quiz_questions_updated_at BEFORE UPDATE ON public.quiz_questions
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER quiz_options_updated_at BEFORE UPDATE ON public.quiz_options
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();

-- ---------------------------------------------------------------------------
-- Row level security
-- ---------------------------------------------------------------------------

ALTER TABLE public.apps            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ui_elements     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.goals           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.goal_steps      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scenarios       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scenario_steps  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quizzes         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_questions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_options    ENABLE ROW LEVEL SECURITY;

-- Catalog material is public to read: the app needs it before sign-in.
CREATE POLICY "catalog is readable" ON public.apps
  FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "catalog is readable" ON public.ui_elements
  FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "catalog is readable" ON public.goals
  FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "catalog is readable" ON public.goal_steps
  FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "catalog is readable" ON public.scenarios
  FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "catalog is readable" ON public.quizzes
  FOR SELECT TO anon, authenticated USING (true);

-- scenario_steps, quiz_questions and quiz_options deliberately get no policies.
-- They are answer keys; runtime roles reach them only through the projections
-- above and the grading function in the next migration.

-- ---------------------------------------------------------------------------
-- Privileges
--
-- InsForge grants broad DML on public tables by default so RLS can arbitrate.
-- The catalog is authored by the team, so revoke first and grant back reads.
-- ---------------------------------------------------------------------------

GRANT USAGE ON SCHEMA public TO anon, authenticated;

REVOKE ALL ON public.apps,
              public.ui_elements,
              public.goals,
              public.goal_steps,
              public.scenarios,
              public.scenario_steps,
              public.quizzes,
              public.quiz_questions,
              public.quiz_options
  FROM anon, authenticated;

GRANT SELECT ON public.apps,
                public.ui_elements,
                public.goals,
                public.goal_steps,
                public.scenarios,
                public.quizzes
  TO anon, authenticated;

GRANT SELECT ON public.quiz_questions_public,
                public.quiz_options_public,
                public.scenario_step_counts
  TO anon, authenticated;
