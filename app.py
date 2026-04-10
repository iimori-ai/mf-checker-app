import streamlit as st
import pandas as pd
import google.generativeai as genai
import fitz  # PyMuPDF
import json
from datetime import datetime, date
import time

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
st.title("会計ソフト × クレカ明細 突合・学習型ツール ⚡")

with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini APIキー", type="password")
    st.divider()
    st.header("🎓 AIへの学習（お手本）")
    user_examples = st.text_area(
        "学習用サンプル",
        placeholder="例: '一括払いからの変更'という行は無視して。",
        height=150
    )

st.subheader("🔑 1. 初期設定")
this_year = datetime.now().year
target_year = st.selectbox("明細の対象年", [this_year, this_year-1, this_year-2], index=0)

st.subheader("🗓️ 2. 期間と残高の設定")
col_start, col_end, col_bal = st.columns(3)
with col_start: start_date = st.date_input("開始日", value=date(target_year, 1, 1))
with col_end: end_date = st.date_input("終了日", value=date(target_year, 12, 31))
with col_bal: start_balance = st.number_input("開始日の期首残高", value=0)

st.subheader("📁 3. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1: csv_file = st.file_uploader("会計ソフトCSV", type=["csv"])
with col2: pdf_files = st.file_uploader("クレカ明細 (PDF)", type=["pdf"], accept_multiple_files=True)

df_ledger = None
if csv_file:
    for enc in ["shift_jis", "utf-8-sig", "cp932"]:
        try:
            csv_file.seek(0)
            df_ledger = pd.read_csv(csv_file, encoding=enc)
            st.success("✅ 会計データ読み込み成功")
            break
        except: continue

if pdf_files and df_ledger is not None:
    if st.button("🚀 解析スタート（タイムアウト対策版）"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            full_text = ""
            for pdf_file in pdf_files:
                doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
                for page in doc: full_text += page.get_text()
            
            # --- 💡 300文字ずつ分割 ＋ 50文字の重複を持たせる ---
            chunk_size = 300
            overlap = 50
            chunks = []
            for i in range(0, len(full_text), chunk_size - overlap):
                chunks.append(full_text[i : i + chunk_size])
            
            chunks = [c for c in chunks if len(c.strip()) > 10]
            total_chunks = len(chunks)
            
            all_ai_data = []
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            for i, chunk in enumerate(chunks):
                # 画面を更新して「動いてる感」を出す（タイムアウト防止の気休め）
                status_text.info(f"🤖 AI解析中... ({i+1}/{total_chunks})")
                progress_bar.progress(int(((i+1)/total_chunks)*85))
                
                prompt = f"""
                明細から「決済取引」のみを抽出しJSONリストで出力。
                年は「{target_year}年」補完。返品はマイナス。
                形式: [{{"date": "YYYY/MM/DD", "description": "摘要", "amount": 1000}}]
                【お手本】: {user_examples}
                ---対象---
                {chunk}
                """
                
                response = model.generate_content(prompt)
                res_text = response.text.strip()
                if "
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1

### 🚀 改善のポイント
* **300文字 ＋ 50文字重複**: 200文字だとぶつ切りになりすぎるため、300文字に設定しました。さらに50文字分、前の束の終わりを次の束の始まりに含めているので、**「データの切れ目での読み落とし」**を防止しています。
* **サーバーへの配慮**: 各ループの終わりに `time.sleep(0.1)` を入れました。これにより、Streamlitのサーバー側との通信が安定しやすくなります。
* **表示の簡略化**: 表の列名を短くし、スマホや狭い画面でもパッと見やすくしました。

これで、長い明細でもタイムアウトせずに最後まで辿り着けるはずです！
もしこれでも止まる場合は、PDFのページ数が多すぎる可能性があります。その時は「1ファイルずつアップロード」して試してみてください。

「サイドバーの学習機能」に何かお手本を入れて試してみましたか？精度に変化はありましたでしょうか？
