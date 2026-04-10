import streamlit as st
import pandas as pd
import google.generativeai as genai
import fitz  # PyMuPDF
import json

# --- 🔐 認証ゲート ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 認証が必要です")
    # 💡 your_secret_password を好きな合言葉に変えてもOKです
    password = st.text_input("合言葉を入力してください", type="password")
    if st.button("ログイン"):
        if password == "351835": 
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("合言葉が正しくありません")
    st.stop()

# --- 🚀 ここからメインツール ---
st.title("MF会計 × クレカ明細 突合ツール ⚡Web公開版")

st.write("---")
st.subheader("🔑 1. 初期設定")
api_key = st.text_input("Gemini APIキーを入力してください", type="password", help="Google AI Studioで取得したキーを入れてください")
st.write("---")

if not api_key:
    st.warning("まずは上にAPIキーを入力してください。")
    st.stop()

st.subheader("📁 2. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1:
    csv_file = st.file_uploader("マネフォ：総勘定元帳 (CSV)", type=["csv"])
with col2:
    pdf_file = st.file_uploader("クレカ明細 (PDF)", type=["pdf"])

# CSV読み込み
df_mf = None
if csv_file is not None:
    try:
        df_mf = pd.read_csv(csv_file, encoding="shift_jis")
        st.success("✅ CSV読み込み完了")
    except Exception as e:
        st.error(f"CSV読み込みエラー: {e}")

# PDF読み込み・解析
if pdf_file is not None and df_mf is not None:
    if st.button("🚀 3. AI解析 ＆ 突合スタート！"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            status_text.info("📄 PDFを読み込んでいます...")
            doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text()
            progress_bar.progress(20)

            status_text.info("🤖 AIが解析中...（1分〜5分ほどかかります）")
            progress_bar.progress(30)
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            prompt = f"""
            以下のテキストから「利用日(YYYY/MM/DD)」「摘要」「金額(数値のみ)」を抽出し、JSON形式のみを出力してください。
            [{{"date": "2026/04/01", "description": "摘要", "amount": 1000}}]
            ---テキスト---
            {text}
            """
            
            safety_settings = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
            
            response = model.generate_content(prompt, safety_settings=safety_settings)
            
            # JSONデータの抽出
            raw_json = response.text.strip()
            if "```json" in raw_json:
                raw_json = raw_json.split("```json")[1].split("```")[0]
            elif "```" in raw_json:
                raw_json = raw_json.split("```")[1].split("```")[0]
            
            ai_data = json.loads(raw_json.strip())
            df_ai = pd.DataFrame(ai_data)
            
            status_text.info("🔍 マッチング中...")
            progress_bar.progress(90)
            
            status_list = []
            mf_all_values = set(df_mf.astype(str).values.flatten())
            
            for _, row in df_ai.iterrows():
                ai_amount = str(row['amount']).replace(',', '')
                if ai_amount in mf_all_values:
                    status_list.append("✅ 登録済")
                else:
                    status_list.append("❌ 連携漏れ")
            
            df_ai['MF登録状況'] = status_list
            status_text.success("✨ 完了！")
            progress_bar.progress(100)
            
            st.write("### 🔍 突合結果")
            st.dataframe(df_ai)
            
        except Exception as e:
            st.error(f"エラー: {e}")
