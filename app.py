import streamlit as st
import pandas as pd
import google.generativeai as genai
import fitz  # PyMuPDF
import json
import math

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
st.title("MF会計 × クレカ明細 突合ツール ⚡タイムアウト対策版")

st.subheader("🔑 1. 初期設定")
api_key = st.text_input("Gemini APIキーを入力してください", type="password")

if not api_key:
    st.warning("まずは上にAPIキーを入力してください。")
    st.stop()

st.subheader("📁 2. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1:
    csv_file = st.file_uploader("マネフォ：総勘定元帳 (CSV)", type=["csv"])
with col2:
    pdf_file = st.file_uploader("クレカ明細 (PDF)", type=["pdf"])

df_mf = None
if csv_file:
    try:
        df_mf = pd.read_csv(csv_file, encoding="shift_jis")
        st.success("✅ CSV読み込み完了")
    except:
        st.error("CSVの読み込みに失敗しました（Shift-JISを確認してください）")

if pdf_file and df_mf is not None:
    if st.button("🚀 3. 解析スタート！"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            # 1. PDF読み込み
            status_text.info("📄 PDFを読み込んでいます...")
            doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
            full_text = "".join([page.get_text() for page in doc])
            
            # 2. テキストを小分けにする (約3000文字ずつ)
            chunk_size = 3000
            chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
            total_chunks = len(chunks)
            
            all_ai_data = []
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            # 3. 小分けにしてAIに依頼
            for i, chunk in enumerate(chunks):
                current_step = i + 1
                percent = int((current_step / total_chunks) * 80) + 10
                status_text.info(f"🤖 AI解析中... ({current_step}/{total_chunks} ブロック目)")
                progress_bar.progress(percent)
                
                prompt = f"""
                以下のテキストから「利用日(YYYY/MM/DD)」「摘要」「金額(数値のみ)」を抽出し、JSON形式のリストのみを出力してください。
                例: [{{"date": "2026/04/01", "description": "店名", "amount": 1000}}]
                ---テキスト---
                {chunk}
                """
                
                response = model.generate_content(prompt)
                
                # JSON抽出
                raw_json = response.text.strip()
                if "```json" in raw_json:
                    raw_json = raw_json.split("```json")[1].split("```")[0]
                elif "```" in raw_json:
                    raw_json = raw_json.split("```")[1].split("```")[0]
                
                all_ai_data.extend(json.loads(raw_json.strip()))

            # 4. 突合
            status_text.info("🔍 マッチング中...")
            df_ai = pd.DataFrame(all_ai_data)
            
            mf_all_values = set(df_mf.astype(str).values.flatten())
            status_list = []
            for _, row in df_ai.iterrows():
                val = str(row['amount']).replace(',', '')
                status_list.append("✅ 登録済" if val in mf_all_values else "❌ 連携漏れ")
            
            df_ai['MF登録状況'] = status_list
            status_text.success("✨ 完了しました！")
            progress_bar.progress(100)
            
            st.write("### 🔍 突合結果")
            st.dataframe(df_ai.style.map(
                lambda x: 'background-color: #ffcccc;' if x == '❌ 連携漏れ' else '', 
                subset=['MF登録状況']
            ))
            
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
