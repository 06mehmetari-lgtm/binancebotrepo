-- TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ═══════════════════════════════════════
-- 1. TICK VERİSİ (Order Book + Trade)
-- ═══════════════════════════════════════
CREATE TABLE market_ticks (
    time           TIMESTAMPTZ NOT NULL,
    symbol         VARCHAR(20) NOT NULL,

    bid_price      DECIMAL(20, 8),
    bid_qty        DECIMAL(20, 8),
    ask_price      DECIMAL(20, 8),
    ask_qty        DECIMAL(20, 8),

    last_price     DECIMAL(20, 8),
    last_qty       DECIMAL(20, 8),
    trade_side     VARCHAR(10),

    book_imbalance FLOAT,
    data_quality   INTEGER DEFAULT 100
);

SELECT create_hypertable('market_ticks', 'time');
CREATE INDEX idx_ticks_symbol ON market_ticks(symbol, time DESC);
ALTER TABLE market_ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol'
);
SELECT add_compression_policy('market_ticks', INTERVAL '7 days');

-- ═══════════════════════════════════════
-- 2. ORDER BOOK SNAPSHOT (Her 1 saniye)
-- ═══════════════════════════════════════
CREATE TABLE order_book_snapshots (
    time          TIMESTAMPTZ NOT NULL,
    symbol        VARCHAR(20) NOT NULL,

    bids          JSONB,
    asks          JSONB,

    mid_price     DECIMAL(20, 8),
    spread        DECIMAL(20, 8),
    spread_pct    FLOAT,
    bid_depth_10  DECIMAL(20, 8),
    ask_depth_10  DECIMAL(20, 8),
    imbalance_10  FLOAT
);

SELECT create_hypertable('order_book_snapshots', 'time');
CREATE INDEX idx_ob_snapshots_symbol ON order_book_snapshots(symbol, time DESC);
ALTER TABLE order_book_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol'
);
SELECT add_compression_policy('order_book_snapshots', INTERVAL '3 days');

-- ═══════════════════════════════════════
-- 3. KLINE (MUM VERİSİ)
-- ═══════════════════════════════════════
CREATE TABLE klines (
    time            TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR(20) NOT NULL,
    "interval"      VARCHAR(5)  NOT NULL,

    open            DECIMAL(20, 8),
    high            DECIMAL(20, 8),
    low             DECIMAL(20, 8),
    close           DECIMAL(20, 8),
    volume          DECIMAL(20, 8),
    quote_volume    DECIMAL(20, 8),
    trades          INTEGER,
    taker_buy_vol   DECIMAL(20, 8),
    taker_buy_quote DECIMAL(20, 8)
);

SELECT create_hypertable('klines', 'time');
CREATE INDEX idx_klines_symbol_interval ON klines(symbol, "interval", time DESC);
ALTER TABLE klines SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('klines', INTERVAL '30 days');

-- ═══════════════════════════════════════
-- 4. KRİPTO'YA ÖZGÜ VERİLER
-- ═══════════════════════════════════════
CREATE TABLE crypto_metrics (
    time              TIMESTAMPTZ NOT NULL,
    symbol            VARCHAR(20) NOT NULL,

    funding_rate      FLOAT,
    open_interest     DECIMAL(30, 8),
    long_short_ratio  FLOAT,
    liquidation_buy   DECIMAL(20, 8),
    liquidation_sell  DECIMAL(20, 8),

    fear_greed_index  INTEGER,

    exchange_inflow   DECIMAL(30, 8),
    exchange_outflow  DECIMAL(30, 8)
);

SELECT create_hypertable('crypto_metrics', 'time');
CREATE INDEX idx_crypto_metrics_symbol ON crypto_metrics(symbol, time DESC);
ALTER TABLE crypto_metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol'
);
SELECT add_compression_policy('crypto_metrics', INTERVAL '14 days');

-- ═══════════════════════════════════════
-- 5. FEATURE STORE
-- ═══════════════════════════════════════
CREATE TABLE features (
    time             TIMESTAMPTZ NOT NULL,
    symbol           VARCHAR(20) NOT NULL,

    -- Fiyat featureları
    rsi_14           FLOAT,
    rsi_7            FLOAT,
    macd_signal      FLOAT,
    macd_hist        FLOAT,
    bb_position      FLOAT,
    atr_14           FLOAT,
    adx_14           FLOAT,

    -- Order book featureları
    imbalance_1      FLOAT,
    imbalance_5      FLOAT,
    imbalance_10     FLOAT,
    spread_z         FLOAT,
    book_pressure    FLOAT,

    -- Kripto özgü
    funding_regime   FLOAT,
    oi_change_1h     FLOAT,
    liq_pressure     FLOAT,
    ls_ratio_z       FLOAT,

    -- Sentiment
    fear_greed_norm  FLOAT,
    reddit_sentiment FLOAT,
    news_sentiment   FLOAT,

    -- Makro
    vix_level        FLOAT,
    dxy_change_1d    FLOAT,
    btc_dominance    FLOAT,

    -- Bağlam
    regime_id        VARCHAR(10),
    drift_status     VARCHAR(20),
    crisis_level     INTEGER,
    market_health    FLOAT,
    drift_quality    FLOAT
);

SELECT create_hypertable('features', 'time');
CREATE INDEX idx_features_symbol ON features(symbol, time DESC);
ALTER TABLE features SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol'
);
SELECT add_compression_policy('features', INTERVAL '14 days');

-- ═══════════════════════════════════════
-- Sürekli aggregate: 1m kline → 1h özet
-- ═══════════════════════════════════════
CREATE MATERIALIZED VIEW klines_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    symbol,
    first(open,  time) AS open,
    max(high)          AS high,
    min(low)           AS low,
    last(close,  time) AS close,
    sum(volume)        AS volume,
    sum(trades)        AS trades
FROM klines
WHERE "interval" = '1m'
GROUP BY bucket, symbol
WITH NO DATA;

SELECT add_continuous_aggregate_policy('klines_1h',
    start_offset => INTERVAL '3 hours',
    end_offset   => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');
