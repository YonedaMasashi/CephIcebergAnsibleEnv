"""PyIceberg サンプル: Hive Metastore カタログ経由で Ceph(RGW) 上に Iceberg テーブルを作る

実行:
    /opt/pyiceberg/bin/python ~/dataplatform-samples/pyiceberg_sample.py
設定は ~/.pyiceberg.yaml の catalog.default を使用
"""
from datetime import datetime

import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError, NoSuchTableError

NAMESPACE = "pyiceberg_demo"
TABLE = f"{NAMESPACE}.sensor"

catalog = load_catalog("default")

# 1) namespace（= HMS の database）
try:
    catalog.create_namespace(NAMESPACE)
    print(f"created namespace: {NAMESPACE}")
except NamespaceAlreadyExistsError:
    pass

# 2) 追記するデータ
data = pa.table(
    {
        "machine_id": pa.array(["M-001", "M-002", "M-003"], pa.string()),
        "temperature": pa.array([41.2, 38.7, 45.1], pa.float64()),
        "measured_at": pa.array([datetime.now()] * 3, pa.timestamp("us")),
    }
)

# 3) テーブル作成（なければ）して追記
try:
    table = catalog.load_table(TABLE)
except NoSuchTableError:
    table = catalog.create_table(TABLE, schema=data.schema)
    print(f"created table: {TABLE} -> {table.location()}")

table.append(data)

# 4) 読み出し
print(table.scan().to_pandas())
print("snapshots:", [s.snapshot_id for s in table.snapshots()])
print("tables in namespace:", catalog.list_tables(NAMESPACE))
