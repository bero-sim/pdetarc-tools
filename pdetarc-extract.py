# https://github.com/bero-sim/pdetarc-tools/blob/main/pdetarc-extract.py
import os
import sys
import json
import tarfile
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

FIXED_TS = 946684800  # 2000-01-01 UTC


# ------------------------
# ログ
# ------------------------
def log(msg, logfile=None):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)

    if logfile:
        with open(logfile, "a", encoding="utf-8-sig") as f:
            f.write(line + "\n")


# ------------------------
# SHA256
# ------------------------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


# ------------------------
# tar open（.gz or tar）
# ------------------------
def open_archive(path):
    if str(path).endswith(".gz"):
        return tarfile.open(path, "r:gz")
    else:
        return tarfile.open(path, "r:")


# ------------------------
# files 展開（tar用）
# ------------------------
def extract_files_from_tar(tar, out_dir):
    members = tar.getmembers()
    file_entries = [m for m in members if m.name.startswith("files/")]

    tmp_dir = out_dir / "__tmp_files__"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    for m in file_entries:
        tar.extract(m, tmp_dir)

    return tmp_dir


# ------------------------
# files 展開（directory用）
# ------------------------
def extract_files_from_dir(base_dir, out_dir):
    src = base_dir / "files"
    tmp_dir = out_dir / "__tmp_files__"

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    shutil.copytree(src, tmp_dir / "files")

    return tmp_dir


# ------------------------
# manifest 復元
# ------------------------
def restore_from_manifest(tmp_dir, out_dir, manifest, logfile):
    files_ok = True

    for entry in manifest["files"]:
        fid = entry["id"]
        rel = entry["path"]

        src = tmp_dir / "files" / fid
        dst = out_dir / rel

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

        os.utime(dst, (FIXED_TS, FIXED_TS))

        if sha256_file(dst) != entry["sha256"]:
            log(f"NG: {rel}", logfile)
            files_ok = False

    return files_ok


# ------------------------
# ルート展開（tar用）
# ------------------------
def extract_root_files_from_tar(tar, out_dir):
    for m in tar.getmembers():
        name = m.name

        if name.startswith("files/"):
            continue
        if name in ("manifest.json", "bundle-hash.json"):
            continue

        tar.extract(m, out_dir)

        path = out_dir / name
        if path.exists():
            os.utime(path, (FIXED_TS, FIXED_TS))


# ------------------------
# ルート展開（directory用）
# ------------------------
def extract_root_files_from_dir(base_dir, out_dir):
    for item in base_dir.iterdir():
        name = item.name

        if name in ("files", "manifest.json", "bundle-hash.json"):
            continue

        dst = out_dir / name

        if item.is_file():
            shutil.copyfile(item, dst)
            os.utime(dst, (FIXED_TS, FIXED_TS))

        elif item.is_dir():
            shutil.copytree(item, dst)
            for root, _, files in os.walk(dst):
                for f in files:
                    p = Path(root) / f
                    os.utime(p, (FIXED_TS, FIXED_TS))


# ------------------------
# 中間ファイル処理対象特定（入力されたパスから、真の .pdetarc ファイルを特定する）
# ------------------------
def find_pdetarc_file(input_path):
    # パターン2: 直接ファイルを指定された場合
    if os.path.isfile(input_path):
        return input_path

    # パターン1 & 3: フォルダを指定された場合
    if os.path.isdir(input_path):
        # フォルダ内にある .pdetarc ファイルを探す
        for root, dirs, files in os.walk(input_path):
            for file in files:
                if file.endswith(".pdetarc"):
                    return os.path.join(root, file)
    
    return None


# ------------------------
# main
# ------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: pdetarc-extract <file_or_folder>")
        return

    # 1. ユーザーがD&Dした「最初の入口」の情報を保持
    raw_input = sys.argv[1]
    drop_path = Path(raw_input)
    # D&Dされた場所の「親フォルダ」を取得（ここを展開基準にする）
    drop_base_dir = drop_path.parent

    # 2. 処理対象の「真のファイル」を探索
    target_str = find_pdetarc_file(raw_input)
    if not target_str:
        print(f"[ERROR] .pdetarc ファイルが見つかりません: {raw_input}")
        input("Press Enter to exit...")
        return

    # 実際に処理するファイル
    input_path = Path(target_str)
    
    # 3. ログファイルは「D&Dされた場所」と同じ階層に作成
    logfile = os.path.join(drop_base_dir, "pdetarc-extract.log")

    print(f"[INFO] ターゲットファイルを特定しました: {input_path}")

    # 4. ガードレールのチェック
    if input_path.is_file():
        if not (input_path.name.endswith(".pdetarc.gz") or input_path.name.endswith(".pdetarc")):
             log(f"ERROR: 非対象ファイルです -> {input_path.name}", logfile)
             sys.exit(1)
    
    # 5. 出力先の決定（D&Dされた階層 + 拡張子を除いた名前）
    stem_name = input_path.name.replace(".pdetarc.gz", "").replace(".pdetarc", "")
    out_dir = drop_base_dir / stem_name

    # 実行開始ログ
    log("==== PDETARC EXTRACT START ====", logfile)
    log(f"入力: {input_path}", logfile)
    log(f"出力: {out_dir}", logfile)

    # 同一パスチェック（安全策）
    if out_dir.resolve() == input_path.resolve():
        log(f"ERROR: 入力と出力が同一パスです。処理を中断します。", logfile)
        sys.exit(1)

    # 既存フォルダの削除と再作成
    if out_dir.exists():
        log(f"既存の出力フォルダを削除して再作成します: {out_dir}", logfile)
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # ------------------------
    # モード分岐
    # ------------------------
    is_dir_mode = input_path.is_dir()

    # ------------------------
    # manifest 読み込み
    # ------------------------
    if is_dir_mode:
        base_dir = input_path
        manifest_path = base_dir / "manifest.json"

        if not manifest_path.exists():
            log("ERROR: manifest.json not found", logfile)
            sys.exit(1)

        manifest = json.load(open(manifest_path, encoding="utf-8"))

        tmp_dir = extract_files_from_dir(base_dir, out_dir)

    else:
        with open_archive(input_path) as tar:
            try:
                mf = tar.extractfile("manifest.json")
                manifest = json.load(mf)
            except Exception:
                log("ERROR: manifest.json not found", logfile)
                sys.exit(1)

            tmp_dir = extract_files_from_tar(tar, out_dir)

            files_ok = restore_from_manifest(tmp_dir, out_dir, manifest, logfile)
            shutil.rmtree(tmp_dir, ignore_errors=True)

            extract_root_files_from_tar(tar, out_dir)

        # tarモードはここで完結
        base_dir = None

    # ------------------------
    # directoryモード復元
    # ------------------------
    if is_dir_mode:
        files_ok = restore_from_manifest(tmp_dir, out_dir, manifest, logfile)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        extract_root_files_from_dir(base_dir, out_dir)

    # ------------------------
    # bundle-hash検証
    # ------------------------
    bundle_ok = True
    bh_path = out_dir / "bundle-hash.json"

    if bh_path.exists():
        try:
            data = json.load(open(bh_path, encoding="utf-8"))

            for b in data:
                archive_file = out_dir / "archive" / "portable-deterministic-archive-v1" / b["file"]

                if archive_file.exists():
                    sha = sha256_file(archive_file)
                    if sha != b["sha256"]:
                        log(f"BUNDLE NG: {b['file']}", logfile)
                        bundle_ok = False
                else:
                    log(f"BUNDLE MISSING: {b['file']}", logfile)
                    bundle_ok = False

        except Exception as e:
            log(f"bundle-hash check error: {str(e)}", logfile)
            bundle_ok = False

    # ------------------------
    # 結果
    # ------------------------
    if bundle_ok and files_ok:
        log("検証結果: OK（完全一致）", logfile)
        code = 0
    else:
        log("検証結果: NG（不一致あり）", logfile)
        code = 1

    log(f"完了: {out_dir}", logfile)
    log("==== PDETARC EXTRACT END ====", logfile)

    sys.exit(code)


if __name__ == "__main__":
    main()
