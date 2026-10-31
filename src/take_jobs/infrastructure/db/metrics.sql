WITH days AS (
  SELECT generate_series((now() AT TIME ZONE :tz)::date - 7, (now() AT TIME ZONE :tz)::date - 1, interval '1 day')::date AS day
), runs AS (
  SELECT (c.started_at AT TIME ZONE :tz)::date AS day,
         c.expected_combinations AS expected,
         (SELECT count(*) FROM collection_run_results r
           WHERE r.run_id = c.id AND r.status = 'success') AS ok
  FROM collection_runs c
  WHERE c.status <> 'running'
)
SELECT round(100.0 * coalesce(sum(r.ok), 0) / sum(coalesce(r.expected, :expected)), 1) AS success_rate_pct
FROM days d LEFT JOIN runs r ON r.day = d.day;
