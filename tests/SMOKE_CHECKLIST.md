# Smoke Checklist Before Launch

## 1) Automated checks

Run from project root:

```bash
/home/vlad/dev/Solo_bot/venv/bin/python -m compileall /home/vlad/dev/Solo_bot -q
```

Run unit tests from writable directory (to avoid log file permission side effects):

```bash
cd /tmp
PYTHONPATH="/home/vlad/dev/Solo_bot" /home/vlad/dev/Solo_bot/venv/bin/python -m unittest discover -s "/home/vlad/dev/Solo_bot/tests" -q
```

Expected result:

- test suite exits with code `0`
- all tests pass

## 1.1) Runtime start convention

- For this project, the canonical full runtime start command is `sudo python3 main.py`
- Do not treat root-owned runtime artifacts in `alembic/` or `/tmp` as a permissions bug by default
- Do not change ownership or permissions during smoke checks unless explicitly requested
- If you need isolated checks, it is still acceptable to run `uvicorn api.main:app` or `npm run dev` separately, but that is not the primary production-like startup path

## 2) Core migration checks

- Start app in staging once and verify DB init passes:
  - account schema migration
  - tg mirror backfill
- Confirm no missing column errors for:
  - `tg_id` mirrors in billing-related tables
  - `created_by_tg_id` for scheduled broadcasts

## 3) Identity and actor checks

Validate these three scenarios end-to-end:

- `tg-only` user:
  - bot flow works
  - actor surface resolves as telegram
- `web-only` user:
  - auth/login works without Telegram
  - billing user is created with internal `users.id`
- `linked` user:
  - link Telegram to existing web account
  - ensure billing remains on same `users.id`
  - Telegram notifications use chat id, not internal id

## 4) Payment and temporary state checks

- Create temporary payment state and complete payment via webhook simulation
- Verify:
  - temporary state is found/cleared correctly
  - payment row uses `user_id` billing relation
  - `tg_id` mirror is populated when Telegram exists
- Ensure no message send attempts to internal `users.id` as `chat_id`

## 5) Gifts and referrals checks

- Gift creation:
  - sender resolves by legacy ref
  - gift stores `sender_user_id` and mirror `sender_tg_id`
- Referral creation:
  - self-referral blocked
  - valid referral stored on billing ids
  - mirrors updated where applicable

## 6) Scheduled broadcasts checks

- Create broadcast by legacy creator ref
- Verify:
  - `created_by_user_id` is resolved when user exists
  - `created_by_tg_id` mirror is stored
  - listing by `created_by_tg_id` works

## 7) Runtime warnings to monitor

- Pydantic warning about `model_custom_emoji_id` is non-blocking but should be cleaned later
- Deprecation warnings for `datetime.utcnow()` are non-blocking but should be migrated to timezone-aware UTC
