import streamlit as st
import pandas as pd
import google.generativeai as genai
import fitz  # PyMuPDF
import json
import time

# --- 🔐 認証ゲート ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 認証が必要です")
    # 💡 合言葉を here に設定！
    password = st.text_input("合言葉を入力してください", type="password")
    if st.button("ログイン"):
        if password == "your_secret_password": 
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("合言葉が正しくありません")
    st.stop()

# --- 🚀 ここからメインツール ---
st.title("MF会計 × クレカ明細 突合ツール ⚡Web公開版")

# ★ サイドバーをやめて、メイン画面にAPIキー入力欄を配置
st.write("---")
st.subheader("🔑 1. 初期設定")
api_key = st.text_input("Gemini APIキーを入力してください", type="password", help="Google AI Studioで取得したキーを入れてください")
st.write("---")

if not api_key:
    st.warning("まずは上にAPIキーを入力してください。入力するとアップロード画面が表示されます。")
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
            status_text.info("【30%】 AIが明細を解析中...（1分〜5分ほどかかります）")
            progress_bar.progress(30)
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            prompt = f"""
            以下のテキストはクレジットカードの明細です。
            データから「利用日(YYYY/MM/DD)」「摘要」「金額(数値のみ)」を抽出し、以下のJSON配列形式のみを出力してください。
            ---抽出元テキスト---
            {text}
            """
            # (以下、突合ロジックは同じです)
            # ... 省略 ...
