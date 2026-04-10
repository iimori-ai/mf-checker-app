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
    password = st.text_input("合言葉を入力してください", type="password")
    if st.button("ログイン"):
        if password == "351835": 
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("合言葉が正しくありません")
    st.stop()

# --- 🚀 メインツール ---
st.title("MF会計 × クレカ明細 突合ツール ⚡複数PDF対応版")

st.subheader("🔑 1. 初期設定")
api_key = st.text_input("Gemini APIキーを入力してください", type="password")

if not api_key:
    st.warning("上にAPIキーを入力すると、アップロード画面が表示されます。")
    st.stop()

st.subheader("📁 2. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1:
    csv_file = st.file_uploader("マネフォ：総勘定元帳 (CSV)", type=["csv"])
with col2:
    # ★ accept_multiple_files=True を追加して複数選択を可能にしました
    pdf_files = st.file_uploader("クレカ明細 (PDF) ※複数可", type=["pdf"], accept_multiple_files=True)

# CSV読み込み（自動判別）
df_mf = None
if csv_file:
    encodings = ["shift_jis", "utf-8-sig", "cp932"]
    for enc in encodings:
        try:
            csv_file.seek(0)
            df_mf = pd.read_csv(csv_file, encoding=enc)
            st.success(f"✅ CSV読み込み完了 ({enc})")
            break
        except:
            continue

# PDF解析と突合
if pdf_files and df_mf is not None:
    st.info(f"現在 {len(pdf_files)} 件のPDFが選択されています。")
    
    if st.button("🚀 3. 全てのPDFを解析 ＆ 突合スタート！"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            # 1. 全てのPDFからテキストを抽出して結合
            status_text.info("📄 全てのPDFからテキストを抽出中...")
            full_text = ""
            for pdf_file in pdf_files:
                doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
                for page in doc:
                    full_text += page.get_text()
            
            # 2. テキストを1000文字ずつに分割（タイムアウト対策）
            chunk_size = 1000
            chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
            chunks = [c for c in chunks if c.strip()]
            total_chunks = len(chunks)
            
            if total_chunks == 0:
                st.error("PDFからテキストを抽出できませんでした。")
                st.stop()
            
            all_ai_data = []
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            # 3. AIにブロックごとに依頼
            for i, chunk in enumerate(chunks):
                current_step = i + 1
                percent = int((current_step / total_chunks) * 90)
                status_text.info(f"🤖 AI解析中... ({current_step}/{total_chunks} ブロック処理中)")
                progress_bar.progress(percent)
                
                prompt = f"""
                以下のテキストから「利用日(YYYY/MM/DD)」「摘要」「金額(数値のみ)」を抽出し、JSON形式のリストのみを出力してください。
                例: [{{"date": "2026/04/01", "description": "店名", "amount": 1000}}]
                ---テキスト---
                {chunk}
                """
                
                response = model.generate_content(prompt)
                res_text = response.text.strip()
                
                # JSON部分の抽出
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

            # 4. 突合
            if not all_ai_data:
                st.warning("AIが有効なデータを抽出できませんでした。")
            else:
                status_text.info("🔍 全データをマネフォと照合中...")
                df_ai = pd.DataFrame(all_ai_data)
                
                # 重複を削除（複数PDFで重なった場合などのため）
                df_ai = df_ai.drop_duplicates().reset_index(drop=True)
                
                mf_all_values = set(df_mf.astype(str).values.flatten())
                status_list = []
                for _, row in df_ai.iterrows():
                    val = str(row.get('amount', '')).replace(',', '').replace('.0', '')
                    status_list.append("✅ 登録済" if val in mf_all_values else "❌ 連携漏れ")
                
                df_ai['MF登録状況'] = status_list
                status_text.success(f"✨ 全 {len(pdf_files)} 件のPDF処理が完了しました！")
                progress_bar.progress(100)
                
                st.write("### 🔍 突合結果（全PDF合算）")
                st.dataframe(df_ai.style.map(
                    lambda x: 'background-color: #ffcccc;' if x == '❌ 連携漏れ' else '', 
                    subset=['MF登録状況']
                ))
            
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
