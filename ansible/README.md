# データ処理基盤 検証環境（Ceph + Iceberg/HMS + Trino + PyIceberg）

VirtualBox 上の Rocky Linux 10（1 台）に以下を構築する Ansible + compose 一式です。
コンテナランタイムは **Podman（rootful）** です。

| コンポーネント | 配置 | 役割 | ポート |
|---|---|---|---|
| Ceph (Tentacle / cephadm) | ホスト（cephadm 管理のコンテナ） | オブジェクトストレージ。RGW が S3 API を提供 | RGW 7480 / Dashboard 8443 |
| PostgreSQL | podman compose | Hive Metastore のバックエンド DB | （公開なし） |
| Hive Metastore 4.0.0 | podman compose | Iceberg カタログ | 9083 |
| Trino 482 | podman compose | SQL エンジン（Iceberg コネクタ） | 8080 |
| PyIceberg | ホストの venv (`/opt/pyiceberg`) | Python から Iceberg を読み書き | - |

Iceberg 自体はサーバーではなく「テーブルフォーマット」なので、Trino と PyIceberg の両方が
同じ HMS カタログ・同じ RGW バケット (`s3a://warehouse/`) を見ることで成立します。

```
 Trino ─┐                     ┌─ PostgreSQL（メタデータ）
        ├─ thrift:9083 ─ HMS ─┤
PyIceberg┘                     └─ Ceph RGW :7480 ─ OSD × N（実データ / Iceberg メタデータ）
   └──────────── データファイルは各クライアントが直接 RGW に読み書き ────────────┘
```

### Podman まわりの構成

- **Ceph**: cephadm が podman で各デーモンを起動し、systemd ユニットとして管理します（cephadm の標準構成）。
- **compose スタック**: `podman compose` を使います。実行エンジンには docker-compose v2 バイナリを使い、`podman.socket`（Docker 互換 API）を経由させています。`depends_on` の `condition: service_healthy` などがそのまま動くためです。
- **rootful で動かす理由**: rootless の既定ネットワーク（pasta）では、コンテナからホスト自身の IP（RGW `:7480`）に接続できないためです。そのため操作コマンドには `sudo` が必要です。
- **OS 再起動後の自動起動**: `podman-restart.service` が `restart: always` のコンテナを起動します。

> Docker CE が既にインストールされている場合、playbook は途中で止まります。先に Docker CE を削除してください（メッセージにコマンドが出ます）。

---

## 0. VM の前提

| 項目 | 推奨値 |
|---|---|
| vCPU | 4 以上 |
| メモリ | 16 GB（最低 12 GB） |
| OS ディスク | 40 GB 以上 |
| 追加ディスク | **20 GB × 3 本（未フォーマット）** ※1 本でも可 |
| ネットワーク | アダプタ1: NAT（インターネット用） / アダプタ2: ホストオンリー（固定 IP） |

### 0-1. 追加ディスクを作る（VM 停止中に）
VirtualBox マネージャ → VM の「設定」→「ストレージ」→ SATA コントローラーに
「ハードディスクを追加」→ 新規作成（VDI / 可変 / 20GB）を 3 回。

起動後に確認:
```bash
lsblk     # sdb, sdc, sdd がパーティションなしで見えていれば OK
```

### 0-2. ホストオンリー側に固定 IP を設定（例: 192.168.56.10）
```bash
nmcli con show                                   # 2 本目の NIC の接続名を確認（例: enp0s8）
sudo nmcli con mod enp0s8 ipv4.method manual ipv4.addresses 192.168.56.10/24
sudo nmcli con up enp0s8
```

---

## 1. ファイルを VM にコピー

Windows の PowerShell から（OpenSSH 同梱）:
```powershell
scp -r .\dataplatform-ansible your_user@192.168.56.10:~/
```

## 2. Ansible をインストール（VM 上）
```bash
sudo dnf install -y ansible-core
ansible --version
```

## 3. 変数を編集
`group_vars/all.yml` の以下は必ず確認:

- `node_ip` … 0-2 で設定した IP
- `osd_devices` … `lsblk` で確認したディスク名
- 各種パスワード / S3 キー（検証用でも変えておくのが無難）

## 4. 実行
```bash
cd ~/dataplatform-ansible
ansible-playbook site.yml -K          # sudo パスワードを聞かれる
```
所要時間の目安: 20〜40 分（イメージのダウンロード量次第）。

段階的に実行したい場合はタグで:
```bash
ansible-playbook site.yml -K --tags base,podman
ansible-playbook site.yml -K --tags ceph
ansible-playbook site.yml -K --tags stack
ansible-playbook site.yml -K --tags pyiceberg
ansible-playbook site.yml -K --tags test      # 疎通確認だけ
```
何度流しても壊れないように作ってあります（bootstrap は初回のみ、OSD/RGW は宣言的に適用）。

毎回 `sudo` を付けるのが面倒なら、`~/.bashrc` に `alias pm='sudo podman'` などを入れておくと楽です。

---

## 5. 動作確認

### Ceph
```bash
sudo cephadm shell -- ceph -s          # HEALTH_OK（OSD 1 本構成でも OK になるよう設定済み）
sudo cephadm shell -- ceph osd tree
```
Dashboard: `https://192.168.56.10:8443`（自己署名証明書の警告は無視）

### Trino
```bash
sudo podman exec -it trino trino
trino> SHOW CATALOGS;
trino> CREATE SCHEMA iceberg.demo;
```
サンプル一括実行:
```bash
sudo podman exec -i trino trino < ~/dataplatform-samples/sample.sql
```
Web UI: `http://192.168.56.10:8080`（ユーザー名は任意の文字列で可）

### PyIceberg
```bash
/opt/pyiceberg/bin/python ~/dataplatform-samples/pyiceberg_sample.py
```
その後 Trino から `SELECT * FROM iceberg.pyiceberg_demo.sensor;` で同じテーブルが見えれば、
**PyIceberg ↔ HMS ↔ Trino が同じ Iceberg テーブルを共有できている**ことの確認になります。

### バケットの中身を見る
```bash
cd /opt/dataplatform
sudo podman compose run --rm --entrypoint sh s3-init -c \
  'aws --endpoint-url $S3_ENDPOINT s3 ls --recursive s3://$BUCKET/ | head -50'
```

---

## 6. 日常操作

```bash
cd /opt/dataplatform
sudo podman compose ps
sudo podman compose logs -f hive-metastore
sudo podman compose stop          # 停止
sudo podman compose start         # 再開
sudo podman ps -a                 # Ceph のコンテナも含めて全部見える
```
Ceph は systemd 管理（`systemctl list-units 'ceph*'`）で、OS 起動時に自動起動します。
compose スタックも `podman-restart.service` で自動起動します。
VM のシャットダウンは普通に `sudo poweroff` で構いません。

### 作り直し（全消去）
```bash
cd /opt/dataplatform && sudo podman compose down -v              # PostgreSQL のメタデータも消える
sudo cephadm rm-cluster --force --zap-osds --fsid $(sudo cephadm shell -- ceph fsid 2>/dev/null | tail -1)
```
その後 `ansible-playbook site.yml -K` で再構築。

---

## 7. トラブルシューティング

| 症状 | 確認・対処 |
|---|---|
| OSD が up にならず待機タスクがタイムアウト | ディスクに古いパーティション/LVM が残っている。`sudo cephadm shell -- ceph orch device ls --refresh` で Available=No なら `sudo wipefs -a /dev/sdX` 後に再実行 |
| VM のディスクが `/dev/nvme0n2` など | `osd_devices` をその名前に変更 |
| hive-metastore が再起動を繰り返す | `sudo podman compose logs hive-metastore`。`ClassNotFoundException: S3AFileSystem` なら JAR のマウント、`Connection refused ... 7480` なら RGW と `node_ip` を確認 |
| `CREATE SCHEMA` で S3 関連エラー | HMS が S3A でディレクトリを作っている。`s3-init` のログでバケット作成成否を確認 |
| Trino の書き込みで条件付き書き込み関連のエラー | `iceberg.properties` に `s3.exclusive-create=false` を追記して `sudo podman compose restart trino` |
| PyIceberg で `SignatureDoesNotMatch` 等 | `~/.pyiceberg.yaml` の endpoint / キーを確認 |
| `short-name resolution enforced but cannot prompt` | イメージ名が短縮形になっている。`docker.io/...` 形式の完全修飾名に直す |
| `podman compose` が「provider が見つからない」と言う | `/etc/containers/containers.conf.d/50-compose.conf` と `/usr/libexec/docker/cli-plugins/docker-compose` の存在を確認。`--tags podman` で再実行 |
| コンテナ名（`postgres` など）が名前解決できない | `aardvark-dns` が入っているか確認（`rpm -q aardvark-dns`） |
| OS 再起動後に compose スタックが起動しない | `systemctl is-enabled podman-restart.service` を確認 |
| メモリ不足で OOM | `group_vars/all.yml` の `trino_mem_limit` / `ceph_osd_memory_target` を下げる |

---

## ファイル構成

```
dataplatform-ansible/
├── ansible.cfg
├── inventory.ini              # localhost（VM 上で実行）
├── group_vars/all.yml         # ★ 変更する変数はここ
├── site.yml                   # playbook 本体（podman 版）
├── templates/
│   ├── osd_spec.yml.j2        # Ceph OSD サービス定義
│   ├── env.j2                 # → /opt/dataplatform/.env
│   ├── hive-site.xml.j2       # → HMS 設定（PostgreSQL / S3A / warehouse）
│   ├── core-site.xml.j2       # → Hadoop S3A 設定
│   ├── iceberg.properties.j2  # → Trino Iceberg カタログ
│   ├── tpch.properties.j2     # → Trino サンプルデータ用カタログ
│   └── pyiceberg.yaml.j2      # → ~/.pyiceberg.yaml
└── files/
    ├── docker-compose.yml     # → /opt/dataplatform/docker-compose.yml（podman compose で実行）
    └── samples/               # → ~/dataplatform-samples/
        ├── sample.sql
        └── pyiceberg_sample.py
```
