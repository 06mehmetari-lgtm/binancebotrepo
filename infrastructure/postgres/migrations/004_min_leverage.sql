-- Min kaldıraç tabanı (dashboard risk limitleri)
ALTER TABLE system_risk_limits
  ADD COLUMN IF NOT EXISTS min_leverage DOUBLE PRECISION NOT NULL DEFAULT 5.0;

UPDATE system_risk_limits
SET min_leverage = 5.0
WHERE id = 1 AND min_leverage < 1;
