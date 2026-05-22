-- Add disqualified status for projects whose video failed content moderation.
-- Disqualified projects are blocked from re-submitting or re-uploading.
alter type project_status add value if not exists 'disqualified';
