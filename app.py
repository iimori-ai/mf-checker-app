import streamlit as st
import pandas as pd
import google.generativeai as genai
import fitz  # PyMuPDF
import json
from datetime import datetime, date
import concurrent.futures
import threading
import io
import time as time_module

# ============================================================
# 🔐 認証ゲート
# ============================================================
def _check_password(input_pw: str) -> bool:
    try:
        correct = st.secrets["auth"]["password"]
    except (KeyError, FileNotFoundError):
        import os
        correct = os.environ.get("APP_PASSWORD", "351835")
    return input_pw == correct


if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 認証が必要です")
    password = st.text_input("合言葉を入力してください", type="password")
    if st.button("ログイン"):
        if _check_password(password):
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("合言葉が正しくありません")
    st.stop()


# ============================================================
# ⚙️ 設定定数
# ============================================================
CHUNK_SIZE            = 30_000   # テキスト1チャンクあたりの文字数
OVERLAP               = 500      # チャンク間の重複文字数（泣き別れ防止）
MAX_WORKERS           = 10       # 並列API送信数
SINGLE_SHOT_THRESHOLD = 35_000   # この文字数未満なら1回のAPI呼び出しで完結
OCR_THRESHOLD         = 50       # get_text() がこの文字数未満のページはスキャンとみなす
OCR_DPI               = 200      # スキャンページのレンダリング解像度（高いほど精度↑、ファイル↑）


# ============================================================
# 🚀 メインUI
# ============================================================
st.title("会計ソフト × クレカ明細 突合・学習型ツール ⚡ ターボ版")

with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini APIキー", type="password")
    st.divider()
    st.header("🎓 AIへの学習（お手本）")
    user_examples = st.text_area(
        "学習用サンプル",
        placeholder="例: '一括払いからの変更'という行は無視して。特定の店名はこう読み替えて。",
        height=200,
    )

st.subheader("🔑 1. 初期設定")
this_year = datetime.now().year
target_year = st.selectbox("明細の対象年", [this_year, this_year - 1, this_year - 2], index=0)

st.subheader("🗓️ 2. 期間と残高の設定")
col_start, col_end, col_bal = st.columns(3)
with col_start:
    start_date = st.date_input("開始日", value=date(target_year, 1, 1))
with col_end:
    end_date = st.date_input("終了日", value=date(target_year, 12, 31))
with col_bal:
    start_balance = st.number_input("開始日の期首残高", value=0)

st.subheader("📁 3. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1:
    csv_file = st.file_uploader("会計ソフトCSV (MF・freee等)", type=["csv"])
with col2:
    pdf_files = st.file_uploader(
        "クレカ明細 (PDF) ※複数可", type=["pdf"], accept_multiple_files=True
    )

# 会計データ読み込み（エンコーディング自動判別）
df_ledger = None
if csv_file:
    loaded = False
    for enc in ["utf-8-sig", "shift_jis", "cp932"]:
        try:
            csv_file.seek(0)
            df_ledger = pd.read_csv(csv_file, encoding=enc)
            st.success(f"✅ 会計データ読み込み成功 ({enc}): {len(df_ledger):,} 件")
            loaded = True
            break
        except Exception:
            continue
    if not loaded:
        st.error(
            "❌ 会計CSVの読み込みに失敗しました。"
            " UTF-8 / Shift-JIS / CP932 いずれでも読み込めませんでした。"
            " ファイルの形式を確認してください。"
        )


# ============================================================
# ヘルパー関数
# ============================================================

def _build_text_prompt(chunk: str, target_year: int, user_examples: str) -> str:
    """テキストチャンク用プロンプト。"""
    return f"""あなたは優秀な経理担当です。以下のクレジットカード明細テキストから「決済取引」のみを抽出し、JSONリストで出力してください。
- 年は「{target_year}年」として補完すること
- 返品・返金は amount をマイナスにすること
- 支払い方法の説明行・合計行・ヘッダー行は含めないこと
- 取引がなければ空リスト [] を返すこと

出力フォーマット（JSONリストのみ・説明文不要）:
[{{"date": "YYYY/MM/DD", "description": "摘要", "amount": 1000}}]

【ユーザー定義の学習例】
{user_examples if user_examples else "特になし"}

---解析対象テキスト---
{chunk}"""


def _build_image_prompt(target_year: int, user_examples: str) -> str:
    """スキャンページ（画像）用プロンプト。"""
    return f"""このクレジットカード明細の画像を読み取り、「決済取引」のみをJSONリストで出力してください。
- 年は「{target_year}年」として補完すること
- 返品・返金は amount をマイナスにすること
- 合計行・ヘッダー行・支払方法説明行は含めないこと
- 取引がなければ空リスト [] を返すこと
- 日本語の明細である可能性が高いです。文字を正確に読み取ってください

出力フォーマット（JSONリストのみ・説明文不要）:
[{{"date": "YYYY/MM/DD", "description": "摘要", "amount": 1000}}]

【ユーザー定義の学習例】
{user_examples if user_examples else "特になし"}"""


def _parse_response(res_text: str) -> list:
    """AI レスポンス（テキスト/画像どちらも）の JSON をパース。"""
    res_text = res_text.strip()
    if "```json" in res_text:
        res_text = res_text.split("```json")[1].split("```")[0]
    elif "```" in res_text:
        res_text = res_text.split("```")[1].split("```")[0]
    data = json.loads(res_text.strip())
    return data if isinstance(data, list) else []


def _call_text_api(args: tuple) -> list:
    """テキストチャンクをAPIに送信。response_mime_type で直接JSONを要求。"""
    model, prompt = args
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json"
            ),
        )
        return _parse_response(response.text)
    except json.JSONDecodeError:
        return []
    except Exception:
        return []


def _call_image_api(args: tuple) -> list:
    """スキャンページ画像を Gemini Vision API に送信しOCR+データ抽出を同時実行。"""
    model, prompt_text, img_bytes = args
    try:
        # PyMuPDF が生成した PNG バイト列を inline_data として送信
        # Pillow 不要（genai SDK が dict 形式のインライン画像を直接サポート）
        response = model.generate_content(
            [
                prompt_text,
                {"mime_type": "image/png", "data": img_bytes},
            ],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json"
            ),
        )
        return _parse_response(response.text)
    except json.JSONDecodeError:
        return []
    except Exception:
        return []


def _normalize_amount(val) -> str:
    """突合用に金額を整数文字列へ正規化（float→int→str で .0 誤変換バグを防止）。"""
    try:
        return str(int(float(str(val).replace(",", "").replace("▲", "-"))))
    except (ValueError, TypeError):
        return str(val)


def _fmt_seconds(s: float) -> str:
    """経過・残り時間を日本語フォーマットで返す。"""
    if s < 60:
        return f"{s:.0f}秒"
    return f"{int(s // 60)}分{int(s % 60)}秒"


# ============================================================
# 🎯 進捗管理クラス（スレッドセーフ）
# ============================================================
class ProgressTracker:
    def __init__(self, total: int):
        self.total      = total
        self.completed  = 0
        self.found      = 0
        self._lock      = threading.Lock()
        self.start_time = time_module.time()

    def record(self, chunk_results: list):
        with self._lock:
            self.completed += 1
            self.found     += len(chunk_results)

    @property
    def elapsed(self) -> float:
        return time_module.time() - self.start_time

    @property
    def eta(self) -> float | None:
        if self.completed == 0:
            return None
        return (self.elapsed / self.completed) * (self.total - self.completed)

    @property
    def pct(self) -> float:
        return self.completed / self.total if self.total > 0 else 0.0


# ============================================================
# メイン解析処理
# ============================================================
if pdf_files and df_ledger is not None:
    if st.button("🚀 爆速解析スタート！"):
        if not api_key:
            st.error("左側のサイドバーにAPIキーを入力してください。")
            st.stop()

        try:
            # ──────────────────────────────────────────────
            # Step 1: PDF を解析してテキストページ / スキャンページを自動振り分け
            # ──────────────────────────────────────────────
            with st.status("📄 PDFを解析中...", expanded=True) as status_box:
                text_page_contents: list[str]  = []  # テキスト抽出できたページの文字列
                scanned_page_images: list[bytes] = []  # スキャンページの PNG バイト列

                for fi, pdf_file in enumerate(pdf_files, 1):
                    st.write(f"ファイル {fi}/{len(pdf_files)}: `{pdf_file.name}`")
                    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
                    try:
                        file_text_pages = 0
                        file_scan_pages = 0
                        for page in doc:
                            raw_text = page.get_text().strip()
                            if len(raw_text) >= OCR_THRESHOLD:
                                # テキストとして抽出できたページ
                                text_page_contents.append(raw_text)
                                file_text_pages += 1
                            else:
                                # スキャン画像ページ → PNG にレンダリング
                                pix = page.get_pixmap(dpi=OCR_DPI)
                                scanned_page_images.append(pix.tobytes("png"))
                                pix = None  # メモリ解放
                                file_scan_pages += 1
                    finally:
                        doc.close()

                    st.write(
                        f"  → テキストページ: **{file_text_pages}** ページ /"
                        f" スキャンページ (OCR): **{file_scan_pages}** ページ"
                    )

                total_text_chars = sum(len(t) for t in text_page_contents)
                full_text = "\n".join(text_page_contents)

                status_box.update(
                    label=(
                        f"📄 PDF解析完了 — テキスト {len(text_page_contents)} ページ"
                        f" / スキャン(OCR) {len(scanned_page_images)} ページ"
                    ),
                    state="complete",
                )

            if not text_page_contents and not scanned_page_images:
                st.warning("PDFからデータを取得できませんでした。")
                st.stop()

            # ──────────────────────────────────────────────
            # Step 2: ジョブキューを作成（テキスト + 画像を統合）
            # ──────────────────────────────────────────────
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")

            text_prompt  = _build_text_prompt  # alias
            image_prompt = _build_image_prompt(target_year, user_examples)

            # テキストチャンク（シングルショット or 分割）
            if full_text.strip():
                if total_text_chars <= SINGLE_SHOT_THRESHOLD:
                    text_chunks = [full_text]
                else:
                    text_chunks = [
                        full_text[i: i + CHUNK_SIZE]
                        for i in range(0, total_text_chars, CHUNK_SIZE - OVERLAP)
                    ]
                    text_chunks = [c for c in text_chunks if len(c.strip()) > 10]
            else:
                text_chunks = []

            # ジョブリスト: type "text" or "image"
            # ("text",  model, prompt_str)
            # ("image", model, prompt_str, img_bytes)
            jobs: list[tuple] = []
            for chunk in text_chunks:
                jobs.append(("text", model, _build_text_prompt(chunk, target_year, user_examples)))
            for img in scanned_page_images:
                jobs.append(("image", model, image_prompt, img))

            total_jobs = len(jobs)
            if total_jobs == 0:
                st.warning("解析するデータがありませんでした。")
                st.stop()

            # モード説明
            mode_parts = []
            if text_chunks:
                mode_parts.append(f"テキスト {len(text_chunks)} チャンク")
            if scanned_page_images:
                mode_parts.append(f"スキャン(OCR) {len(scanned_page_images)} ページ")
            mode_label = f"⚡ {' + '.join(mode_parts)} を最大 {min(MAX_WORKERS, total_jobs)} 並列で解析"

            # ──────────────────────────────────────────────
            # Step 3: 並列 AI 解析 + リアルタイム進捗
            # ──────────────────────────────────────────────
            st.markdown("---")
            st.markdown(f"**{mode_label}**")
            progress_bar = st.progress(0)
            col_a, col_b, col_c = st.columns(3)
            ph_chunks = col_a.empty()
            ph_found  = col_b.empty()
            ph_time   = col_c.empty()
            ph_status = st.empty()

            tracker     = ProgressTracker(total_jobs)
            all_ai_data: list[dict] = []

            def _refresh_ui():
                progress_bar.progress(int(tracker.pct * 90))
                ph_chunks.metric("ジョブ進捗", f"{tracker.completed} / {tracker.total}")
                ph_found.metric("取引（発見済み）", f"{tracker.found} 件")
                eta     = tracker.eta
                eta_str = f"残り約 {_fmt_seconds(eta)}" if eta is not None else "計算中..."
                ph_time.metric("⏱️ 経過時間", _fmt_seconds(tracker.elapsed), delta=eta_str)
                ph_status.info(
                    f"⚡ 解析中... {tracker.completed}/{tracker.total} 完了 | "
                    f"取引 {tracker.found} 件発見 | "
                    f"経過 {_fmt_seconds(tracker.elapsed)}"
                )

            def _execute_job(job: tuple) -> list:
                """ジョブタイプに応じてテキスト or 画像 API を呼び分ける。"""
                if job[0] == "text":
                    _, mdl, prompt = job
                    return _call_text_api((mdl, prompt))
                else:
                    _, mdl, prompt, img_bytes = job
                    return _call_image_api((mdl, prompt, img_bytes))

            _refresh_ui()
            workers = min(MAX_WORKERS, total_jobs)
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_execute_job, job): i for i, job in enumerate(jobs)}
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    all_ai_data.extend(result)
                    tracker.record(result)
                    _refresh_ui()

            # ──────────────────────────────────────────────
            # Step 4: データ集計と突合
            # ──────────────────────────────────────────────
            if not all_ai_data:
                ph_status.warning("データが抽出されませんでした。PDFの内容を確認してください。")
            else:
                ph_status.info("🔍 会計データと最終照合中...")

                df_ai = pd.DataFrame(all_ai_data).drop_duplicates()
                df_ai["date"] = pd.to_datetime(df_ai["date"], errors="coerce")
                df_ai = df_ai.dropna(subset=["date"])

                mask  = (df_ai["date"].dt.date >= start_date) & (df_ai["date"].dt.date <= end_date)
                df_ai = df_ai.loc[mask].sort_values("date").reset_index(drop=True)

                if df_ai.empty:
                    ph_status.warning("指定された期間内にデータが見つかりませんでした。")
                else:
                    # 残高計算
                    df_ai["計算残高"] = start_balance - df_ai["amount"].cumsum()
                    current_bal = df_ai["計算残高"].iloc[-1]

                    # 突合
                    ledger_values      = set(df_ledger.astype(str).values.flatten())
                    normalized_amounts = df_ai["amount"].apply(_normalize_amount)
                    df_ai["状況"] = normalized_amounts.apply(
                        lambda v: "✅ 済" if v in ledger_values else "❌ 漏れ"
                    )
                    df_ai["date"] = df_ai["date"].dt.strftime("%m/%d")

                    # 完了
                    progress_bar.progress(100)
                    total_elapsed = _fmt_seconds(tracker.elapsed)
                    ph_status.success(f"✨ 解析完了！ — {total_elapsed} で {tracker.found} 件を処理")
                    ph_chunks.metric("ジョブ進捗", f"{tracker.total} / {tracker.total} ✅")
                    ph_time.metric("⏱️ 総処理時間", total_elapsed)
                    st.balloons()

                    # サマリー
                    st.markdown("---")
                    st.subheader("📊 解析結果")
                    total_count   = len(df_ai)
                    matched_count = (df_ai["状況"] == "✅ 済").sum()
                    missing_count = total_count - matched_count

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("💰 最終計算残高", f"{int(current_bal):,} 円")
                    m2.metric("📋 合計件数",      f"{total_count} 件")
                    m3.metric("✅ 一致",           f"{matched_count} 件")
                    m4.metric(
                        "❌ 漏れ", f"{missing_count} 件",
                        delta=f"-{missing_count}" if missing_count else None,
                        delta_color="inverse",
                    )

                    st.dataframe(
                        df_ai.style.map(
                            lambda x: "background-color: #ffcccc; color: #900;" if x == "❌ 漏れ" else "",
                            subset=["状況"],
                        ),
                        use_container_width=True,
                    )

                    csv_bytes = df_ai.to_csv(index=False).encode("utf-8-sig")
                    st.download_button(
                        label="📥 結果をCSVでダウンロード",
                        data=io.BytesIO(csv_bytes),
                        file_name=f"突合結果_{start_date}_{end_date}.csv",
                        mime="text/csv",
                    )

        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
            raise
