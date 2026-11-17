WITH ranked AS (
  SELECT *, row_number() OVER (
    PARTITION BY unit_id, event_type, event_id ORDER BY "$path"
  ) AS delivery_number
  FROM coldchain_dev.events
)
SELECT unit_id, date_trunc('hour', from_iso8601_timestamp(observed_at)) AS observation_hour,
       count(*) AS readings, min(temperature) AS minimum_c, max(temperature) AS maximum_c,
       avg(temperature) AS average_c
FROM ranked
WHERE delivery_number = 1 AND event_type = 'reading.received'
GROUP BY 1, 2
ORDER BY 1, 2;
