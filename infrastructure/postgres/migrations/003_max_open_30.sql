-- Max açık pozisyon: 3 → 30 (paper çoklu sinyal)
UPDATE system_risk_limits
SET max_open_positions = 30,
    updated_at = NOW(),
    updated_by = 'migration_003'
WHERE id = 1 AND max_open_positions < 30;
