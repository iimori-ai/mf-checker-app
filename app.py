import streamlit as st
import pandas as pd
import google.generativeai as genai
import fitz  # PyMuPDF
import json
from datetime import datetime, date

# --- 🔐 認証ゲート ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 認証が必要です")
    password = st.text_input("合言葉を入力してください", type="password")
    if st.button("ログイン"):
        if password == "351835": 
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("合言葉が正しくありません")
    st.stop()

# --- 🚀 メインツール ---
st.title("会計ソフト × クレカ明細 突合・残高検証ツール ⚡")

st.subheader("🔑 1. 初期設定")
col_api, col_year = st.columns([2, 1])
with col_api:
    api_key = st.text_input("Gemini APIキー", type="password")
with col_year:
    this_year = datetime.now().year
    target_year = st.selectbox("明細の対象年", [this_year, this_year-1, this_year-2], index=0)

st.subheader("🗓️ 2. 期間と残高の設定")
col_start, col_end, col_bal = st.columns(3)
with col_start:
    start_date = st.date_input("開始日", value=date(target_year, 1, 1), format="YYYY/MM/DD")
with col_end:
    end_date = st.date_input("終了日", value=date(target_year, 12, 31), format="YYYY/MM/DD")
with col_bal:
    # 指定期間の開始日時点での、カード会社への未払金残高などを入力
    start_balance = st.number_input("開始日の期首残高", value=0, help="開始日の前日時点での未払金残高などを入力してください。")

if not api_key:
    st.warning("APIキーを入力してください。")
    st.stop()

st.subheader("📁 3. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1:
    csv_file = st.file_uploader("会計ソフトCSV (MF・freee等)", type=["csv"])
with col2:
    pdf_files = st.file_uploader("クレカ明細 (PDF)", type=["pdf"], accept_multiple_files=True)

# CSV読み込み
df_ledger = None
if csv_file:
    encodings = ["shift_jis", "utf-8-sig", "cp932"]
    for enc in encodings:
        try:
            csv_file.seek(0)
            df_ledger = pd.read_csv(csv_file, encoding=enc)
            st.success(f"✅ 会計データ読み込み完了")
            break
        except:
            continue

# メイン処理
if pdf_files and df_ledger is not None:
    if st.button("🚀 解析 ＆ 残高検証スタート！"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            full_text = ""
            for pdf_file in pdf_files:
                doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
                for page in doc:
                    full_text += page.get_text()
            
            chunk_size = 1000
            chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
            chunks = [c for c in chunks if c.strip()]
            total_chunks = len(chunks)
            
            all_ai_data = []
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            for i, chunk in enumerate(chunks):
                status_text.info(f"🤖 AI解析中... ({i+1}/{total_chunks})")
                progress_bar.progress(int(((i+1)/total_chunks)*80))
                
                prompt = f"""
                明細から「決済取引」のみを抽出しJSONで出力してください。
                年は「{target_year}年」として補完してください。
                形式: [{{"date": "YYYY/MM/DD", "description": "店名", "amount": 1000}}]
                ---テキスト---
                {chunk}
                """
                response = model.generate_content(prompt)
                res_text = response.text.strip()
                if "
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1

---

### ✨ 追加機能のポイント

1.  **残高スライド計算機能**:
    * `開始日の期首残高` を起点として、1件ずつ `amount` を引いて（または返金なら足して）いきます。
    * 計算結果は **「明細上の計算残高」** 列として表示されます。
    * これにより、PDF明細の最後にある「今回のお支払い合計」や「未払金残高」と、ツールの最終行の数字が一致するか一目で確認できます。

2.  **freee対応（汎用マッチング）**:
    * freeeのCSVはMFと列名が違いますが、このツールは**「CSV内のどこかのセルにその金額が存在するか」**を全検索する仕組みにしています。
    * そのため、freeeから出した「仕訳帳」でも「現預金レポート」でも、そのままアップロードすれば突合が可能です。

3.  **アメックス等のマイナス表記対応**:
    * アメックス特有の「▲」によるマイナス表記や、小数点（.0）がCSVに含まれていても、内部で正規化してマッチングするように強化しました。

### 💡 運用のコツ
カード会社のPDFには「今回の請求額」が載っていますが、これは「前月までの残高 ＋ 今月の利用 ＋ 手数料 － 支払い」の結果です。
ツールに入力する **「期首残高」** は、**「開始日の前日時点での、カード会社に対する未払金残高」** を入力すると、最も正確に検証ができます！

GitHubを更新して、計算結果が実際の明細と合うか確認してみてください。
