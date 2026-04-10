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
        if password == "your_secret_password": 
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("合言葉が正しくありません")
    st.stop()

# --- 🚀 メインツール ---
st.title("MF会計 × クレカ明細 突合ツール ⚡期間指定対応版")

st.subheader("🔑 1. 初期設定")
col_api, col_year = st.columns([2, 1])
with col_api:
    api_key = st.text_input("Gemini APIキー", type="password")
with col_year:
    this_year = datetime.now().year
    target_year = st.selectbox("明細の対象年", [this_year, this_year-1, this_year-2], index=0)

# ★ 期間選択機能の追加
st.subheader("🗓️ 2. 解析・突合する期間を指定")
col_start, col_end = st.columns(2)
with col_start:
    start_date = st.date_input("開始日", value=date(target_year, 1, 1), format="YYYY/MM/DD")
with col_end:
    end_date = st.date_input("終了日", value=date(target_year, 12, 31), format="YYYY/MM/DD")

if not api_key:
    st.warning("上にAPIキーを入力すると、アップロード画面が表示されます。")
    st.stop()

st.subheader("📁 3. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1:
    csv_file = st.file_uploader("マネフォ：総勘定元帳 (CSV)", type=["csv"])
with col2:
    pdf_files = st.file_uploader("クレカ明細 (PDF) ※複数可", type=["pdf"], accept_multiple_files=True)

# CSV読み込み（自動判別）
df_mf = None
if csv_file:
    encodings = ["shift_jis", "utf-8-sig", "cp932"]
    for enc in encodings:
        try:
            csv_file.seek(0)
            df_mf = pd.read_csv(csv_file, encoding=enc)
            st.success(f"✅ CSV読み込み完了")
            break
        except:
            continue

# PDF解析と突合
if pdf_files and df_mf is not None:
    if st.button("🚀 4. 指定期間を解析 ＆ 突合スタート！"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            # 1. 全てのPDFからテキスト抽出
            full_text = ""
            for pdf_file in pdf_files:
                doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
                for page in doc:
                    full_text += page.get_text()
            
            # 2. テキスト分割
            chunk_size = 1000
            chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
            chunks = [c for c in chunks if c.strip()]
            total_chunks = len(chunks)
            
            all_ai_data = []
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            # 3. AI解析
            for i, chunk in enumerate(chunks):
                status_text.info(f"🤖 AI解析中... ({i+1}/{total_chunks})")
                progress_bar.progress(int(((i+1)/total_chunks)*80))
                
                prompt = f"""
                あなたは優秀な経理アシスタントです。明細から「決済取引」のみを抽出し、JSONリストで出力してください。
                年がない場合は「{target_year}年」として補完してください。
                形式: [{{"date": "YYYY/MM/DD", "description": "店名", "amount": 1000}}]
                ---テキスト---
                {chunk}
                """
                
                response = model.generate_content(prompt)
                res_text = response.text.strip()
                if "```json" in res_text:
                    res_text = res_text.split("```json")[1].split("```")[0]
                elif "```" in res_text:
                    res_text = res_text.split("```")[1].split("```")[0]
                
                try:
                    data = json.loads(res_text.strip())
                    if isinstance(data, list):
                        all_ai_data.extend(data)
                except:
                    continue

            # 4. 期間フィルタリングと突合
            if not all_ai_data:
                st.warning("データが抽出されませんでした。")
            else:
                df_ai = pd.DataFrame(all_ai_data).drop_duplicates()
                
                # 日付を変換してフィルタリング
                df_ai['date'] = pd.to_datetime(df_ai['date'], errors='coerce')
                df_ai = df_ai.dropna(subset=['date']) # 変換に失敗した行を消す
                
                # ★ ここで指定された期間（start_date 〜 end_date）に絞り込む
                mask = (df_ai['date'].dt.date >= start_date) & (df_ai['date'].dt.date <= end_date)
                df_ai = df_ai.loc[mask].sort_values('date')
                
                if df_ai.empty:
                    st.warning("指定された期間内のデータが見つかりませんでした。")
                else:
                    status_text.info("🔍 指定期間のデータをマネフォと照合中...")
                    mf_all_values = set(df_mf.astype(str).values.flatten())
                    
                    status_list = []
                    for _, row in df_ai.iterrows():
                        val = str(row.get('amount', '')).replace(',', '').replace('.0', '')
                        status_list.append("✅ 登録済" if val in mf_all_values else "❌ 連携漏れ")
                    
                    df_ai['MF登録状況'] = status_list
                    # 表示用に日付を綺麗な文字列に戻す
                    df_ai['date'] = df_ai['date'].dt.strftime('%Y/%m/%d')
                    
                    status_text.success(f"✨ {start_date} 〜 {end_date} の解析が完了しました！")
                    progress_bar.progress(100)
                    
                    st.write(f"### 🔍 突合結果 ({len(df_ai)}件)")
                    st.dataframe(df_ai.style.map(
                        lambda x: 'background-color: #ffcccc;' if x == '❌ 連携漏れ' else '', 
                        subset=['MF登録状況']
                    ))
            
        except Exception as e:
            st.error(f"エラー: {e}")
