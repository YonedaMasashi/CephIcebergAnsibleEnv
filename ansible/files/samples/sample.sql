-- Trino CLI で実行:
--   sudo podman exec -it trino trino
-- もしくは: sudo podman exec -i trino trino < ~/dataplatform-samples/sample.sql

-- 1) スキーマ作成（場所は HMS の既定 = s3a://warehouse/demo.db）
CREATE SCHEMA IF NOT EXISTS iceberg.demo;

-- 2) TPC-H のサンプルデータから Iceberg テーブルを作成（CTAS）
CREATE TABLE IF NOT EXISTS iceberg.demo.orders
WITH (format = 'PARQUET', partitioning = ARRAY['orderpriority'])
AS SELECT orderkey, custkey, orderstatus, totalprice, orderdate, orderpriority
   FROM tpch.tiny.orders;

-- 3) 集計
SELECT orderpriority, count(*) AS cnt, round(sum(totalprice), 2) AS total
FROM iceberg.demo.orders
GROUP BY orderpriority
ORDER BY orderpriority;

-- 4) Iceberg のメタデータテーブル
SELECT snapshot_id, operation, committed_at FROM iceberg.demo."orders$snapshots";
SELECT file_path, record_count FROM iceberg.demo."orders$files" LIMIT 5;

-- 5) 更新系（Iceberg なので行単位の DELETE / UPDATE が可能）
DELETE FROM iceberg.demo.orders WHERE orderstatus = 'P';
SELECT snapshot_id, operation FROM iceberg.demo."orders$snapshots";

-- 6) PyIceberg サンプル（pyiceberg_sample.py）実行後なら、そのテーブルも見える
-- SELECT * FROM iceberg.pyiceberg_demo.sensor;
