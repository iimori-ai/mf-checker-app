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
        # 💡 your_secret_password を自分の好きな言葉に変えて保存してください
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
    # 選択期間の最初の日の残高（前日までの未払金残高など）
    start_balance = st.number_input("開始日の期首残高", value=0)

if not api_key:
    st.warning("APIキーを入力してください。")
    st.stop()

st.subheader("📁 3. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1:
    csv_file = st.file_uploader("会計ソフトCSV (MF・freee等)", type=["csv"])
with col2:
    pdf_files = st.file_uploader("クレカ明細 (PDF) ※複数可", type=["pdf"], accept_multiple_files=True)

# --- CSV読み込み (MF/freee 汎用) ---
df_ledger = None
if csv_file:
    encodings = ["shift_jis", "utf-8-sig", "cp932"]
    for enc in encodings:
        try:
            csv_file.seek(0)
            df_ledger = pd.read_csv(csv_file, encoding=enc)
            st.success(f"✅ 会計データ読み込み成功 ({enc})")
            break
        except:
            continue

# --- メイン処理 ---
if pdf_files and df_ledger is not None:
    if st.button("🚀 解析 ＆ 残高検証スタート！"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            # 1. PDFからテキスト抽出
            status_text.info("📄 PDFを読み込んでいます...")
            full_text = ""
            for pdf_file in pdf_files:
                doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
                for page in doc:
                    full_text += page.get_text()
            
            # 2. 1000文字ずつに分割 (タイムアウト対策)
            chunk_size = 1000
            chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
            chunks = [c for c in chunks if c.strip()]
            total_chunks = len(chunks)
            
            all_ai_data = []
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            # 3. AI解析
            for i, chunk in enumerate(chunks):
                current_step = i + 1
                percent = int((current_step / total_chunks) * 80)
                status_text.info(f"🤖 AI解析中... ({current_step}/{total_chunks})")
                progress_bar.progress(percent)
                
                prompt = f"""
                明細から「決済取引（利用日、摘要、金額）」を抽出し、JSONリストのみで出力してください。
                年は「{target_year}年」としてください。返品・返金は金額をマイナスにしてください。
                形式: [{{"date": "YYYY/MM/DD", "description": "店名", "amount": 1000}}]
                ---テキスト---
                {chunk}
                """
                response = model.generate_content(prompt)
                res_text = response.text.strip()
                
                # JSON部分を安全に抽出 (エラーの元を修正)
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

            # 4. フィルタリング・残高計算・突合
            if not all_ai_data:
                st.warning("有効なデータを抽出できませんでした。")
            else:
                df_ai = pd.DataFrame(all_ai_data).drop_duplicates()
                df_ai['date'] = pd.to_datetime(df_ai['date'], errors='coerce')
                df_ai = df_ai.dropna(subset=['date'])
                
                # 期間で絞り込み ＆ 日付順に並び替え
                mask = (df_ai['date'].dt.date >= start_date) & (df_ai['date'].dt.date <= end_date)
                df_ai = df_ai.loc[mask].sort_values('date').reset_index(drop=True)
                
                # --- 残高の自動計算 ---
                current_bal = start_balance
                calc_balances = []
                for _, row in df_ai.iterrows():
                    # 支出をマイナス、返金をプラスとして計算 (未払金残高の減少)
                    current_bal -= row['amount']
                    calc_balances.append(current_bal)
                
                df_ai['明細上の計算残高'] = calc_balances
                
                # --- 突合 (freee/MF 汎用) ---
                status_text.info("🔍 会計ソフトのデータと照合中...")
                # 会計データの全セルを検索対象にする
                ledger_values = set(df_ledger.astype(str).values.flatten())
                
                status_list = []
                for _, row in df_ai.iterrows():
                    # 金額の表記揺れを吸収
                    amt_str = str(row.get('amount', '')).replace(',', '').replace('.0', '').replace('▲', '-')
                    if amt_str in ledger_values:
                        status_list.append("✅ 登録済")
                    else:
                        status_list.append("❌ 連携漏れ")
                
                df_ai['登録状況'] = status_list
                df_ai['date'] = df_ai['date'].dt.strftime('%Y/%m/%d')
                
                status_text.success("✨ 解析 ＆ 検証完了！")
                progress_bar.progress(100)
                
                st.write(f"### 🔍 突合結果 & 残高推移 ({len(df_ai)}件)")
                st.metric("最終的な計算上の残高", f"{current_bal:,} 円")
                
                st.dataframe(df_ai.style.map(
                    lambda x: 'background-color: #ffcccc; color: #900;' if x == '❌ 連携漏れ' else '', 
                    subset=['登録状況']
                ))
            
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
