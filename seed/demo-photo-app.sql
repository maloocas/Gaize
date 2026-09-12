-- Demo content for the hackathon scope: one small mock photo app, one goal,
-- one verified scenario, one quiz. Idempotent - safe to re-run.

INSERT INTO public.apps (slug, name, description)
VALUES ('photo-desk', 'Photo Desk',
        'A small mock photo editor used to demo gaze-driven learning.')
ON CONFLICT (slug) DO UPDATE
SET name = EXCLUDED.name, description = EXCLUDED.description;

-- The buttons Gaize can explain out loud.
INSERT INTO public.ui_elements (app_id, element_key, label, explanation, dwell_ms, confirm_ms, sort_order)
SELECT a.id, v.element_key, v.label, v.explanation, v.dwell_ms, v.confirm_ms, v.sort_order
FROM public.apps a
CROSS JOIN (VALUES
  ('open-photo', 'Open',
   'Opens a photo from your library so you can work on it.', 600, 1200, 1),
  ('crop',       'Crop',
   'Trims the edges of the photo. Nothing is deleted until you save.', 600, 1200, 2),
  ('filters',    'Filters',
   'Changes the colour and mood of the photo. You can undo this later.', 600, 1200, 3),
  ('undo',       'Undo',
   'Takes back the last change you made.', 500, 1000, 4),
  ('export',     'Export',
   'Saves a copy of the photo to your computer. This is the first step to sending it to someone.', 700, 1400, 5),
  ('format-png', 'PNG',
   'Chooses the PNG file type. PNG keeps the picture sharp and is a safe everyday choice.', 600, 1200, 6),
  ('confirm-export', 'Save',
   'Finishes the export and writes the file. This is the last step.', 700, 1500, 7),
  ('delete',     'Delete',
   'Removes this photo. This one cannot be undone, so listen before you confirm.', 900, 2000, 8)
) AS v(element_key, label, explanation, dwell_ms, confirm_ms, sort_order)
WHERE a.slug = 'photo-desk'
ON CONFLICT (app_id, element_key) DO UPDATE
SET label       = EXCLUDED.label,
    explanation = EXCLUDED.explanation,
    dwell_ms    = EXCLUDED.dwell_ms,
    confirm_ms  = EXCLUDED.confirm_ms,
    sort_order  = EXCLUDED.sort_order;

-- The goal the website walks you through.
INSERT INTO public.goals (app_id, slug, title, description, difficulty, sort_order)
SELECT a.id, 'export-a-photo', 'Export a photo',
       'Learn how to save a copy of a photo as a PNG file.', 'beginner', 1
FROM public.apps a WHERE a.slug = 'photo-desk'
ON CONFLICT (app_id, slug) DO UPDATE
SET title = EXCLUDED.title, description = EXCLUDED.description;

INSERT INTO public.goal_steps (goal_id, step_number, instruction, element_id)
SELECT g.id, v.step_number, v.instruction, e.id
FROM public.goals g
JOIN public.apps a ON a.id = g.app_id
CROSS JOIN (VALUES
  (1, 'Look at Export and listen to what it does.',            'export'),
  (2, 'Look at PNG to pick the file type.',                    'format-png'),
  (3, 'Look at Save and hold your gaze to finish the export.', 'confirm-export')
) AS v(step_number, instruction, element_key)
JOIN public.ui_elements e ON e.app_id = a.id AND e.element_key = v.element_key
WHERE a.slug = 'photo-desk' AND g.slug = 'export-a-photo'
ON CONFLICT (goal_id, step_number) DO UPDATE
SET instruction = EXCLUDED.instruction, element_id = EXCLUDED.element_id;

-- The scenario the website verifies live, in order.
INSERT INTO public.scenarios (app_id, goal_id, slug, title, prompt, time_limit_seconds, strict_order)
SELECT a.id, g.id, 'export-as-png', 'Export this photo as a PNG',
       'Save a copy of the photo on screen as a PNG file.', 180, TRUE
FROM public.apps a
JOIN public.goals g ON g.app_id = a.id AND g.slug = 'export-a-photo'
WHERE a.slug = 'photo-desk'
ON CONFLICT (app_id, slug) DO UPDATE
SET title = EXCLUDED.title, prompt = EXCLUDED.prompt;

INSERT INTO public.scenario_steps (scenario_id, step_number, element_id, expected_action, hint, required)
SELECT s.id, v.step_number, e.id, v.expected_action, v.hint, TRUE
FROM public.scenarios s
JOIN public.apps a ON a.id = s.app_id
CROSS JOIN (VALUES
  (1, 'export',         'confirm', 'Start with the button that saves a copy.'),
  (2, 'format-png',     'confirm', 'Pick the file type that keeps the picture sharp.'),
  (3, 'confirm-export', 'confirm', 'Finish by saving.')
) AS v(step_number, element_key, expected_action, hint)
JOIN public.ui_elements e ON e.app_id = a.id AND e.element_key = v.element_key
WHERE a.slug = 'photo-desk' AND s.slug = 'export-as-png'
ON CONFLICT (scenario_id, step_number) DO UPDATE
SET element_id = EXCLUDED.element_id, expected_action = EXCLUDED.expected_action, hint = EXCLUDED.hint;

-- The quiz, graded server-side.
INSERT INTO public.quizzes (goal_id, title, pass_threshold)
SELECT g.id, 'Exporting a photo', 0.67
FROM public.goals g
JOIN public.apps a ON a.id = g.app_id
WHERE a.slug = 'photo-desk' AND g.slug = 'export-a-photo'
  AND NOT EXISTS (SELECT 1 FROM public.quizzes q WHERE q.goal_id = g.id);

INSERT INTO public.quiz_questions (quiz_id, question_number, prompt, explanation, element_id)
SELECT q.id, v.question_number, v.prompt, v.explanation, e.id
FROM public.quizzes q
JOIN public.goals g ON g.id = q.goal_id
JOIN public.apps a ON a.id = g.app_id
CROSS JOIN (VALUES
  (1, 'Which button saves a copy of your photo to your computer?',
      'Export makes a copy. The original photo stays where it was.', 'export'),
  (2, 'You changed the colours and do not like them. What do you use?',
      'Undo takes back the last change, so it is safe to experiment.', 'undo'),
  (3, 'Which action cannot be undone?',
      'Delete removes the photo for good. Gaize explains it before you confirm.', 'delete')
) AS v(question_number, prompt, explanation, element_key)
JOIN public.ui_elements e ON e.app_id = a.id AND e.element_key = v.element_key
WHERE a.slug = 'photo-desk'
ON CONFLICT (quiz_id, question_number) DO UPDATE
SET prompt = EXCLUDED.prompt, explanation = EXCLUDED.explanation, element_id = EXCLUDED.element_id;

INSERT INTO public.quiz_options (question_id, option_number, text, is_correct)
SELECT qq.id, v.option_number, v.text, v.is_correct
FROM public.quiz_questions qq
JOIN public.quizzes q ON q.id = qq.quiz_id
JOIN public.goals g ON g.id = q.goal_id
JOIN public.apps a ON a.id = g.app_id
CROSS JOIN (VALUES
  (1, 1, 'Crop',   FALSE),
  (1, 2, 'Export', TRUE),
  (1, 3, 'Filters',FALSE),
  (2, 1, 'Undo',   TRUE),
  (2, 2, 'Delete', FALSE),
  (2, 3, 'Open',   FALSE),
  (3, 1, 'Crop',   FALSE),
  (3, 2, 'Export', FALSE),
  (3, 3, 'Delete', TRUE)
) AS v(question_number, option_number, text, is_correct)
WHERE a.slug = 'photo-desk' AND qq.question_number = v.question_number
ON CONFLICT (question_id, option_number) DO UPDATE
SET text = EXCLUDED.text, is_correct = EXCLUDED.is_correct;
