import streamlit as st
import pandas as pd
import google.generativeai as genai
import fitz  # PyMuPDF
import json
from datetime import datetime, date
import concurrent.futures
import io

# ============================================================
# 🔐 認証ゲート
# ============================================================
# パスワードは st.secrets["password"] から読み込む。
# secrets.toml に以下を記述してください:
#   [auth]
#   password = "your_secret_password"
# ローカル開発用のフォールバックとして環境変数 APP_PASSWORD も対応。
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
# 🚀 メインツール
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

# ============================================================
# 会計データ読み込み（エンコーディング自動判別）
# ============================================================
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

def _build_prompt(chunk: str, target_year: int, user_examples: str) -> str:
    return f"""あなたは優秀な経理担当です。明細から「決済取引」のみを抽出しJSONリストで出力。
年は「{target_year}年」として補完。返品や返金は金額をマイナス表記にすること。
出力はJSONリストのみとし、説明文は一切不要。

形式: [{{"date": "YYYY/MM/DD", "description": "摘要", "amount": 1000}}]

【ユーザー定義の学習例】
{user_examples if user_examples else "特になし"}

---解析対象テキスト---
{chunk}"""


def _parse_response(res_text: str) -> list:
    """AI レスポンスからマークダウン装飾を剥がして JSON パース。"""
    res_text = res_text.strip()
    if "```json" in res_text:
        res_text = res_text.split("```json")[1].split("```")[0]
    elif "```" in res_text:
        res_text = res_text.split("```")[1].split("```")[0]
    data = json.loads(res_text.strip())
    if isinstance(data, list):
        return data
    return []


def _call_api(args: tuple) -> list:
    """1チャンクをAPIに送信し、抽出データリストを返す。並列実行用。"""
    model, prompt = args
    try:
        response = model.generate_content(prompt)
        return _parse_response(response.text)
    except json.JSONDecodeError:
        return []  # パース失敗チャンクは空リストで継続
    except Exception:
        return []  # API エラー（レート制限など）も空リストで継続


def _normalize_amount(val) -> str:
    """突合用に金額を整数文字列へ正規化。float の .0 誤変換バグを修正。"""
    try:
        return str(int(float(str(val).replace(",", "").replace("▲", "-"))))
    except (ValueError, TypeError):
        return str(val)


# ============================================================
# メイン解析処理
# ============================================================
if pdf_files and df_ledger is not None:
    if st.button("🚀 爆速解析スタート！"):
        if not api_key:
            st.error("左側のサイドバーにAPIキーを入力してください。")
            st.stop()

        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            # --------------------------------------------------
            # Step 1: PDF テキストを一括抽出
            # --------------------------------------------------
            status_text.info("📄 PDFからテキストを抽出中...")
            page_texts: list[str] = []
            for pdf_file in pdf_files:
                doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
                try:
                    for page in doc:
                        page_texts.append(page.get_text())
                finally:
                    doc.close()  # 確実にメモリ解放
            full_text = "".join(page_texts)  # O(n) 結合

            if not full_text.strip():
                st.warning("PDFからテキストを抽出できませんでした。スキャン画像PDFは非対応です。")
                st.stop()

            # --------------------------------------------------
            # Step 2: チャンク分割（サイズ拡大で API 呼び出し回数を削減）
            # --------------------------------------------------
            CHUNK_SIZE = 15_000  # 5,000 → 15,000 に拡大（API呼び出し回数が約1/3に）
            OVERLAP = 500
            chunks = [
                full_text[i: i + CHUNK_SIZE]
                for i in range(0, len(full_text), CHUNK_SIZE - OVERLAP)
            ]
            chunks = [c for c in chunks if len(c.strip()) > 10]
            total_chunks = len(chunks)

            # --------------------------------------------------
            # Step 3: AI による並列高速解析
            # --------------------------------------------------
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")

            prompts = [_build_prompt(c, target_year, user_examples) for c in chunks]
            args_list = [(model, p) for p in prompts]

            all_ai_data: list[dict] = []
            MAX_WORKERS = min(5, total_chunks)  # 同時並列数（Gemini 無料枠でも安全な上限）

            status_text.info(f"⚡ {total_chunks} チャンクを {MAX_WORKERS} 並列で爆速解析中...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(_call_api, arg): idx for idx, arg in enumerate(args_list)}
                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    all_ai_data.extend(result)
                    completed += 1
                    progress_bar.progress(int((completed / total_chunks) * 90))
                    status_text.info(f"⚡ 爆速解析中... ({completed}/{total_chunks})")

            # --------------------------------------------------
            # Step 4: データ集計と突合
            # --------------------------------------------------
            if not all_ai_data:
                st.warning("データが抽出されませんでした。PDFの内容を確認してください。")
            else:
                df_ai = pd.DataFrame(all_ai_data).drop_duplicates()
                df_ai["date"] = pd.to_datetime(df_ai["date"], errors="coerce")
                df_ai = df_ai.dropna(subset=["date"])

                # 期間フィルタ & ソート
                mask = (df_ai["date"].dt.date >= start_date) & (df_ai["date"].dt.date <= end_date)
                df_ai = df_ai.loc[mask].sort_values("date").reset_index(drop=True)

                if df_ai.empty:
                    st.warning("指定された期間内にデータが見つかりませんでした。")
                else:
                    # 残高計算（cumsum でベクトル演算・高速）
                    df_ai["計算残高"] = start_balance - df_ai["amount"].cumsum()
                    current_bal = df_ai["計算残高"].iloc[-1]

                    # 突合ロジック（isin でベクトル演算・高速）
                    status_text.info("🔍 会計データと最終照合中...")
                    ledger_values = set(df_ledger.astype(str).values.flatten())

                    # ▶ float→int→str 正規化でバグを修正
                    normalized_amounts = df_ai["amount"].apply(_normalize_amount)
                    df_ai["状況"] = normalized_amounts.apply(
                        lambda v: "✅ 済" if v in ledger_values else "❌ 漏れ"
                    )

                    # 表示用日付フォーマット（最後に変換）
                    df_ai["date"] = df_ai["date"].dt.strftime("%m/%d")

                    status_text.success("✨ 解析完了！")
                    progress_bar.progress(100)
                    st.balloons()

                    # サマリー表示
                    total_count = len(df_ai)
                    matched_count = (df_ai["状況"] == "✅ 済").sum()
                    missing_count = total_count - matched_count

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("最終的な計算残高", f"{int(current_bal):,} 円")
                    m2.metric("合計件数", f"{total_count} 件")
                    m3.metric("✅ 一致", f"{matched_count} 件")
                    m4.metric("❌ 漏れ", f"{missing_count} 件", delta=f"-{missing_count}" if missing_count else None, delta_color="inverse")

                    # 結果テーブル
                    st.dataframe(
                        df_ai.style.map(
                            lambda x: "background-color: #ffcccc; color: #900;" if x == "❌ 漏れ" else "",
                            subset=["状況"],
                        )
                    )

                    # CSV ダウンロード
                    csv_bytes = df_ai.to_csv(index=False).encode("utf-8-sig")
                    st.download_button(
                        label="📥 結果をCSVでダウンロード",
                        data=io.BytesIO(csv_bytes),
                        file_name=f"突合結果_{start_date}_{end_date}.csv",
                        mime="text/csv",
                    )

        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
            raise  # デバッグ時に Streamlit のトレースバックを表示
