-- Run in the coldchain-dev workgroup. For demo, replace coldchain_dev with coldchain_demo.
-- Microbatch retry overlap is at least once: deduplicate by stable domain event identity.
WITH ranked AS (
  SELECT *, row_number() OVER (
    PARTITION BY unit_id, event_type, event_id ORDER BY "$path"
  ) AS delivery_number
  FROM coldchain_dev.events
)
SELECT event_type, unit_id, reading_id, incident_id, observed_at, temperature,
       json_extract_scalar(detail, '$.status') AS incident_status
FROM ranked
WHERE delivery_number = 1
ORDER BY observed_at NULLS LAST, event_type
LIMIT 200;
