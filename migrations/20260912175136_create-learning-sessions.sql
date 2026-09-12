-- Gaize learner state: a session in the app, the raw gaze event feed it emits,
-- and the scenario verification the website watches live.
--
-- The learner's app only ever appends gaze events. Everything derived from them
-- (which scenario steps are done, whether the session passed, goal mastery) is
-- maintained by triggers here, so the website can trust what it renders and a
-- learner cannot mark their own scenario complete.

-- ---------------------------------------------------------------------------
-- Sessions
-- ---------------------------------------------------------------------------

CREATE TABLE public.learning_sessions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  app_id          UUID NOT NULL REFERENCES public.apps(id) ON DELETE CASCADE,
  goal_id         UUID REFERENCES public.goals(id) ON DELETE SET NULL,
  scenario_id     UUID REFERENCES public.scenarios(id) ON DELETE SET NULL,
  mode            TEXT NOT NULL DEFAULT 'free'
                  CHECK (mode IN ('free', 'goal', 'scenario')),
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'completed', 'failed', 'abandoned')),
  -- Server-maintained: seeded from the scenario, advanced by verification.
  steps_total     INTEGER NOT NULL DEFAULT 0 CHECK (steps_total >= 0),
  steps_completed INTEGER NOT NULL DEFAULT 0 CHECK (steps_completed >= 0),
  started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ended_at        TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (steps_completed <= steps_total),
  CHECK (mode <> 'scenario' OR scenario_id IS NOT NULL),
  CHECK (mode <> 'goal' OR goal_id IS NOT NULL)
);

CREATE INDEX idx_learning_sessions_user_id ON public.learning_sessions(user_id);
CREATE INDEX idx_learning_sessions_user_active
  ON public.learning_sessions(user_id, started_at DESC) WHERE status = 'active';

-- ---------------------------------------------------------------------------
-- The gaze event feed. Append-only: this is the evidence trail.
-- ---------------------------------------------------------------------------

CREATE TABLE public.gaze_events (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  session_id  UUID NOT NULL REFERENCES public.learning_sessions(id) ON DELETE CASCADE,
  user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  element_id  UUID REFERENCES public.ui_elements(id) ON DELETE SET NULL,
  -- hover               gaze settled on the element
  -- explanation_played  the spoken description was played
  -- confirm             gaze held again to commit
  -- action              the app actually performed the action
  -- dismiss             the learner looked away instead of committing
  event_type  TEXT NOT NULL
              CHECK (event_type IN ('hover', 'explanation_played', 'confirm', 'action', 'dismiss')),
  dwell_ms    INTEGER CHECK (dwell_ms IS NULL OR dwell_ms >= 0),
  -- Tracker confidence for this fixation, 0..1.
  confidence  REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_gaze_events_session ON public.gaze_events(session_id, occurred_at);
CREATE INDEX idx_gaze_events_user_id ON public.gaze_events(user_id);
CREATE INDEX idx_gaze_events_element_id ON public.gaze_events(element_id);

-- ---------------------------------------------------------------------------
-- Per-session verification state, written only by the verification trigger
-- ---------------------------------------------------------------------------

CREATE TABLE public.session_step_progress (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id       UUID NOT NULL REFERENCES public.learning_sessions(id) ON DELETE CASCADE,
  user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  scenario_step_id UUID NOT NULL REFERENCES public.scenario_steps(id) ON DELETE CASCADE,
  step_number      INTEGER NOT NULL CHECK (step_number > 0),
  required         BOOLEAN NOT NULL DEFAULT TRUE,
  status           TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'completed', 'skipped', 'failed')),
  completed_at     TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (session_id, scenario_step_id)
);

CREATE INDEX idx_session_step_progress_session ON public.session_step_progress(session_id, step_number);
CREATE INDEX idx_session_step_progress_user_id ON public.session_step_progress(user_id);
CREATE INDEX idx_session_step_progress_pending
  ON public.session_step_progress(session_id, step_number) WHERE status = 'pending';

-- ---------------------------------------------------------------------------
-- Quiz attempts
-- ---------------------------------------------------------------------------

CREATE TABLE public.quiz_attempts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  quiz_id         UUID NOT NULL REFERENCES public.quizzes(id) ON DELETE CASCADE,
  session_id      UUID REFERENCES public.learning_sessions(id) ON DELETE SET NULL,
  status          TEXT NOT NULL DEFAULT 'in_progress'
                  CHECK (status IN ('in_progress', 'submitted')),
  -- Server-maintained by submit_quiz_attempt().
  score           INTEGER NOT NULL DEFAULT 0 CHECK (score >= 0),
  total_questions INTEGER NOT NULL DEFAULT 0 CHECK (total_questions >= 0),
  passed          BOOLEAN,
  started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  submitted_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (score <= total_questions)
);

CREATE INDEX idx_quiz_attempts_user_id ON public.quiz_attempts(user_id);
CREATE INDEX idx_quiz_attempts_quiz_id ON public.quiz_attempts(quiz_id);

CREATE TABLE public.quiz_answers (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id         UUID NOT NULL REFERENCES public.quiz_attempts(id) ON DELETE CASCADE,
  user_id            UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  question_id        UUID NOT NULL REFERENCES public.quiz_questions(id) ON DELETE CASCADE,
  selected_option_id UUID REFERENCES public.quiz_options(id) ON DELETE SET NULL,
  -- NULL while the attempt is open; filled in at submission, which is when the
  -- learner is meant to find out how they did.
  is_correct         BOOLEAN,
  answered_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (attempt_id, question_id)
);

CREATE INDEX idx_quiz_answers_attempt_id ON public.quiz_answers(attempt_id);
CREATE INDEX idx_quiz_answers_user_id ON public.quiz_answers(user_id);

-- ---------------------------------------------------------------------------
-- Rolled-up mastery per goal: what the learner knows, what to review
-- ---------------------------------------------------------------------------

CREATE TABLE public.user_goal_progress (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  goal_id           UUID NOT NULL REFERENCES public.goals(id) ON DELETE CASCADE,
  status            TEXT NOT NULL DEFAULT 'not_started'
                    CHECK (status IN ('not_started', 'in_progress', 'completed', 'needs_review')),
  mastery_score     NUMERIC(4, 3) NOT NULL DEFAULT 0
                    CHECK (mastery_score >= 0 AND mastery_score <= 1),
  scenarios_passed  INTEGER NOT NULL DEFAULT 0 CHECK (scenarios_passed >= 0),
  quizzes_passed    INTEGER NOT NULL DEFAULT 0 CHECK (quizzes_passed >= 0),
  last_practiced_at TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, goal_id)
);

CREATE INDEX idx_user_goal_progress_user_id ON public.user_goal_progress(user_id);

-- ---------------------------------------------------------------------------
-- Ownership helpers (SECURITY DEFINER so RLS policies do not re-enter RLS)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.owns_session(p_session_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.learning_sessions
    WHERE id = p_session_id AND user_id = auth.uid()
  );
$$;

CREATE OR REPLACE FUNCTION public.owns_quiz_attempt(p_attempt_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.quiz_attempts
    WHERE id = p_attempt_id AND user_id = auth.uid()
  );
$$;

-- ---------------------------------------------------------------------------
-- Seeding a scenario session with its checklist
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.seed_session_steps()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_total INTEGER;
BEGIN
  IF NEW.scenario_id IS NULL THEN
    RETURN NEW;
  END IF;

  INSERT INTO public.session_step_progress
    (session_id, user_id, scenario_step_id, step_number, required)
  SELECT NEW.id, NEW.user_id, st.id, st.step_number, st.required
  FROM public.scenario_steps st
  WHERE st.scenario_id = NEW.scenario_id;

  SELECT COUNT(*) INTO v_total
  FROM public.scenario_steps
  WHERE scenario_id = NEW.scenario_id AND required;

  UPDATE public.learning_sessions
  SET steps_total = v_total
  WHERE id = NEW.id;

  RETURN NEW;
END;
$$;

CREATE TRIGGER learning_sessions_seed_steps
AFTER INSERT ON public.learning_sessions
FOR EACH ROW EXECUTE FUNCTION public.seed_session_steps();

-- ---------------------------------------------------------------------------
-- Live task verification: match each gaze event against the answer key
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.verify_scenario_progress()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_session      public.learning_sessions%ROWTYPE;
  v_strict       BOOLEAN;
  v_goal_id      UUID;
  v_step_id      UUID;
  v_step_number  INTEGER;
  v_next_pending INTEGER;
  v_completed    INTEGER;
  v_remaining    INTEGER;
  v_channel      TEXT;
BEGIN
  SELECT * INTO v_session
  FROM public.learning_sessions
  WHERE id = NEW.session_id;

  IF NOT FOUND OR v_session.status <> 'active' OR v_session.scenario_id IS NULL THEN
    RETURN NEW;
  END IF;

  SELECT strict_order, COALESCE(goal_id, v_session.goal_id)
    INTO v_strict, v_goal_id
  FROM public.scenarios
  WHERE id = v_session.scenario_id;

  -- The earliest still-pending step this event satisfies.
  SELECT ssp.id, ssp.step_number
    INTO v_step_id, v_step_number
  FROM public.session_step_progress ssp
  JOIN public.scenario_steps st ON st.id = ssp.scenario_step_id
  WHERE ssp.session_id = NEW.session_id
    AND ssp.status = 'pending'
    AND st.element_id = NEW.element_id
    AND st.expected_action = NEW.event_type
  ORDER BY ssp.step_number
  LIMIT 1;

  IF v_step_id IS NULL THEN
    RETURN NEW;
  END IF;

  -- Under strict ordering, only the next outstanding step may be satisfied.
  IF v_strict THEN
    SELECT MIN(step_number) INTO v_next_pending
    FROM public.session_step_progress
    WHERE session_id = NEW.session_id AND status = 'pending';

    IF v_step_number IS DISTINCT FROM v_next_pending THEN
      RETURN NEW;
    END IF;
  END IF;

  UPDATE public.session_step_progress
  SET status = 'completed', completed_at = NEW.occurred_at
  WHERE id = v_step_id;

  SELECT COUNT(*) FILTER (WHERE status = 'completed' AND required),
         COUNT(*) FILTER (WHERE status = 'pending' AND required)
    INTO v_completed, v_remaining
  FROM public.session_step_progress
  WHERE session_id = NEW.session_id;

  UPDATE public.learning_sessions
  SET steps_completed = v_completed
  WHERE id = NEW.session_id;

  v_channel := 'session:' || NEW.session_id::TEXT;

  PERFORM realtime.publish(
    v_channel,
    'step_completed',
    jsonb_build_object(
      'session_id',      NEW.session_id,
      'step_number',     v_step_number,
      'steps_completed', v_completed,
      'steps_total',     v_session.steps_total,
      'occurred_at',     NEW.occurred_at
    )
  );

  -- Every required step done: the scenario is passed.
  IF v_remaining = 0 THEN
    UPDATE public.learning_sessions
    SET status = 'completed', ended_at = NOW()
    WHERE id = NEW.session_id;

    IF v_goal_id IS NOT NULL THEN
      INSERT INTO public.user_goal_progress
        (user_id, goal_id, status, mastery_score, scenarios_passed, last_practiced_at)
      VALUES
        (NEW.user_id, v_goal_id, 'completed', 1.0, 1, NOW())
      ON CONFLICT (user_id, goal_id) DO UPDATE
      SET status            = 'completed',
          mastery_score     = GREATEST(public.user_goal_progress.mastery_score, 1.0),
          scenarios_passed  = public.user_goal_progress.scenarios_passed + 1,
          last_practiced_at = NOW();
    END IF;

    PERFORM realtime.publish(
      v_channel,
      'session_completed',
      jsonb_build_object(
        'session_id',      NEW.session_id,
        'steps_completed', v_completed,
        'steps_total',     v_session.steps_total
      )
    );
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER gaze_events_verify_scenario
AFTER INSERT ON public.gaze_events
FOR EACH ROW EXECUTE FUNCTION public.verify_scenario_progress();

-- ---------------------------------------------------------------------------
-- Quiz answers may not change once the attempt is submitted
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.guard_quiz_answer_writes()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_status TEXT;
BEGIN
  SELECT status INTO v_status
  FROM public.quiz_attempts
  WHERE id = NEW.attempt_id;

  IF v_status = 'submitted' THEN
    RAISE EXCEPTION 'quiz attempt % is already submitted', NEW.attempt_id
      USING ERRCODE = 'check_violation';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER quiz_answers_guard_writes
BEFORE INSERT OR UPDATE ON public.quiz_answers
FOR EACH ROW EXECUTE FUNCTION public.guard_quiz_answer_writes();

-- ---------------------------------------------------------------------------
-- Grading. The only path that reads the answer key on a learner's behalf.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.submit_quiz_attempt(p_attempt_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_attempt   public.quiz_attempts%ROWTYPE;
  v_goal_id   UUID;
  v_threshold NUMERIC;
  v_total     INTEGER;
  v_score     INTEGER;
  v_passed    BOOLEAN;
  v_feedback  JSONB;
BEGIN
  SELECT * INTO v_attempt
  FROM public.quiz_attempts
  WHERE id = p_attempt_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'quiz attempt not found' USING ERRCODE = 'no_data_found';
  END IF;

  IF v_attempt.user_id <> auth.uid() THEN
    RAISE EXCEPTION 'not your quiz attempt' USING ERRCODE = 'insufficient_privilege';
  END IF;

  IF v_attempt.status = 'submitted' THEN
    RAISE EXCEPTION 'quiz attempt already submitted' USING ERRCODE = 'check_violation';
  END IF;

  SELECT q.goal_id, q.pass_threshold INTO v_goal_id, v_threshold
  FROM public.quizzes q
  WHERE q.id = v_attempt.quiz_id;

  -- Grade every answer against the hidden key.
  UPDATE public.quiz_answers a
  SET is_correct = COALESCE(o.is_correct, FALSE)
  FROM public.quiz_options o
  WHERE a.attempt_id = p_attempt_id
    AND o.id = a.selected_option_id;

  -- Unanswered questions count as wrong.
  UPDATE public.quiz_answers
  SET is_correct = FALSE
  WHERE attempt_id = p_attempt_id AND selected_option_id IS NULL;

  SELECT COUNT(*) INTO v_total
  FROM public.quiz_questions
  WHERE quiz_id = v_attempt.quiz_id;

  SELECT COUNT(*) INTO v_score
  FROM public.quiz_answers
  WHERE attempt_id = p_attempt_id AND is_correct;

  v_passed := v_total > 0 AND (v_score::NUMERIC / v_total) >= v_threshold;

  UPDATE public.quiz_attempts
  SET status          = 'submitted',
      score           = v_score,
      total_questions = v_total,
      passed          = v_passed,
      submitted_at    = NOW()
  WHERE id = p_attempt_id;

  IF v_goal_id IS NOT NULL THEN
    INSERT INTO public.user_goal_progress
      (user_id, goal_id, status, mastery_score, quizzes_passed, last_practiced_at)
    VALUES (
      v_attempt.user_id,
      v_goal_id,
      CASE WHEN v_passed THEN 'completed' ELSE 'needs_review' END,
      CASE WHEN v_total > 0 THEN ROUND(v_score::NUMERIC / v_total, 3) ELSE 0 END,
      CASE WHEN v_passed THEN 1 ELSE 0 END,
      NOW()
    )
    ON CONFLICT (user_id, goal_id) DO UPDATE
    SET status            = CASE WHEN v_passed THEN 'completed' ELSE 'needs_review' END,
        mastery_score     = GREATEST(
                              public.user_goal_progress.mastery_score,
                              CASE WHEN v_total > 0 THEN ROUND(v_score::NUMERIC / v_total, 3) ELSE 0 END
                            ),
        quizzes_passed    = public.user_goal_progress.quizzes_passed
                            + CASE WHEN v_passed THEN 1 ELSE 0 END,
        last_practiced_at = NOW();
  END IF;

  -- End-of-quiz feedback: what they got right, what to review.
  SELECT COALESCE(jsonb_agg(f ORDER BY f.question_number), '[]'::JSONB)
  INTO v_feedback
  FROM (
    SELECT q.id                AS question_id,
           q.question_number,
           q.prompt,
           q.explanation,
           a.selected_option_id,
           COALESCE(a.is_correct, FALSE) AS is_correct,
           correct.id           AS correct_option_id,
           correct.text         AS correct_option_text
    FROM public.quiz_questions q
    LEFT JOIN public.quiz_answers a
      ON a.question_id = q.id AND a.attempt_id = p_attempt_id
    LEFT JOIN LATERAL (
      SELECT o.id, o.text
      FROM public.quiz_options o
      WHERE o.question_id = q.id AND o.is_correct
      ORDER BY o.option_number
      LIMIT 1
    ) correct ON TRUE
    WHERE q.quiz_id = v_attempt.quiz_id
  ) f;

  RETURN jsonb_build_object(
    'attempt_id',      p_attempt_id,
    'score',           v_score,
    'total_questions', v_total,
    'passed',          v_passed,
    'pass_threshold',  v_threshold,
    'questions',       v_feedback
  );
END;
$$;

REVOKE ALL ON FUNCTION public.submit_quiz_attempt(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.submit_quiz_attempt(UUID) TO authenticated;

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------

CREATE TRIGGER learning_sessions_updated_at BEFORE UPDATE ON public.learning_sessions
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER session_step_progress_updated_at BEFORE UPDATE ON public.session_step_progress
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER quiz_attempts_updated_at BEFORE UPDATE ON public.quiz_attempts
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER quiz_answers_updated_at BEFORE UPDATE ON public.quiz_answers
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();
CREATE TRIGGER user_goal_progress_updated_at BEFORE UPDATE ON public.user_goal_progress
  FOR EACH ROW EXECUTE FUNCTION system.update_updated_at();

-- ---------------------------------------------------------------------------
-- Row level security: every learner sees only their own records
-- ---------------------------------------------------------------------------

ALTER TABLE public.learning_sessions     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gaze_events           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.session_step_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_attempts         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_answers          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_goal_progress    ENABLE ROW LEVEL SECURITY;

CREATE POLICY "read own sessions" ON public.learning_sessions
  FOR SELECT TO authenticated USING (user_id = (SELECT auth.uid()));
CREATE POLICY "start own sessions" ON public.learning_sessions
  FOR INSERT TO authenticated WITH CHECK (user_id = (SELECT auth.uid()));
CREATE POLICY "end own sessions" ON public.learning_sessions
  FOR UPDATE TO authenticated
  USING (user_id = (SELECT auth.uid()))
  WITH CHECK (user_id = (SELECT auth.uid()));

CREATE POLICY "read own gaze events" ON public.gaze_events
  FOR SELECT TO authenticated USING (user_id = (SELECT auth.uid()));
CREATE POLICY "append own gaze events" ON public.gaze_events
  FOR INSERT TO authenticated
  WITH CHECK (user_id = (SELECT auth.uid()) AND public.owns_session(session_id));

CREATE POLICY "read own step progress" ON public.session_step_progress
  FOR SELECT TO authenticated USING (user_id = (SELECT auth.uid()));

CREATE POLICY "read own attempts" ON public.quiz_attempts
  FOR SELECT TO authenticated USING (user_id = (SELECT auth.uid()));
CREATE POLICY "start own attempts" ON public.quiz_attempts
  FOR INSERT TO authenticated WITH CHECK (user_id = (SELECT auth.uid()));

CREATE POLICY "read own answers" ON public.quiz_answers
  FOR SELECT TO authenticated USING (user_id = (SELECT auth.uid()));
CREATE POLICY "record own answers" ON public.quiz_answers
  FOR INSERT TO authenticated
  WITH CHECK (user_id = (SELECT auth.uid()) AND public.owns_quiz_attempt(attempt_id));
CREATE POLICY "revise own answers" ON public.quiz_answers
  FOR UPDATE TO authenticated
  USING (user_id = (SELECT auth.uid()))
  WITH CHECK (user_id = (SELECT auth.uid()));

CREATE POLICY "read own progress" ON public.user_goal_progress
  FOR SELECT TO authenticated USING (user_id = (SELECT auth.uid()));

-- ---------------------------------------------------------------------------
-- Privileges
--
-- Revoke the broad defaults, then grant back exactly what the learner's client
-- needs. Derived columns stay out of every client-facing grant.
-- ---------------------------------------------------------------------------

REVOKE ALL ON public.learning_sessions,
              public.gaze_events,
              public.session_step_progress,
              public.quiz_attempts,
              public.quiz_answers,
              public.user_goal_progress
  FROM anon, authenticated;

-- Sessions: start one, read it, and close it out. Step counts are the server's.
GRANT SELECT, INSERT ON public.learning_sessions TO authenticated;
GRANT UPDATE (status, ended_at) ON public.learning_sessions TO authenticated;

-- Gaze events are append-only history.
GRANT SELECT, INSERT ON public.gaze_events TO authenticated;

-- Verification results are read-only to the learner and the website.
GRANT SELECT ON public.session_step_progress TO authenticated;

-- Quiz attempts: open one and read it. Scores come from submit_quiz_attempt().
GRANT SELECT, INSERT ON public.quiz_attempts TO authenticated;

-- Answers: record and revise a choice while the attempt is open.
GRANT SELECT, INSERT ON public.quiz_answers TO authenticated;
GRANT UPDATE (selected_option_id, answered_at) ON public.quiz_answers TO authenticated;

GRANT SELECT ON public.user_goal_progress TO authenticated;

-- ---------------------------------------------------------------------------
-- Realtime: the website watches a live session
-- ---------------------------------------------------------------------------

INSERT INTO realtime.channels (pattern, description, enabled)
VALUES ('session:%', 'Live scenario verification for one learning session', true)
ON CONFLICT (pattern) DO UPDATE
SET description = EXCLUDED.description,
    enabled     = EXCLUDED.enabled;

ALTER TABLE realtime.channels ENABLE ROW LEVEL SECURITY;

-- A learner may only subscribe to their own session's channel.
CREATE POLICY subscribe_own_session
ON realtime.channels FOR SELECT
TO authenticated
USING (
  pattern = 'session:%'
  AND public.owns_session(
        NULLIF(split_part(realtime.channel_name(), ':', 2), '')::UUID
      )
);
