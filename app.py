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
    # your_secret_password を自分の好きな言葉に変えて保存してください
    password = st.text_input("合言葉を入力してください", type="password")
    if st.button("ログイン"):
        if password == "351835": 
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("合言葉が正しくありません")
    st.stop()

# --- 🚀 メインツール ---
st.title("会計ソフト × クレカ明細 突合・学習型ツール ⚡ ターボ版")

with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini APIキー", type="password")
    st.divider()
    st.header("🎓 AIへの学習（お手本）")
    user_examples = st.text_area(
        "学習用サンプル",
        placeholder="例: '一括払いからの変更'という行は無視して。特定の店名はこう読み替えて。",
        height=200
    )

st.subheader("🔑 1. 初期設定")
this_year = datetime.now().year
target_year = st.selectbox("明細の対象年", [this_year, this_year-1, this_year-2], index=0)

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
    pdf_files = st.file_uploader("クレカ明細 (PDF) ※複数可", type=["pdf"], accept_multiple_files=True)

# 会計データ読み込み (エンコーディング自動判別)
df_ledger = None
if csv_file:
    for enc in ["shift_jis", "utf-8-sig", "cp932"]:
        try:
            csv_file.seek(0)
            df_ledger = pd.read_csv(csv_file, encoding=enc)
            st.success(f"✅ 会計データ読み込み成功 ({enc})")
            break
        except:
            continue

# メイン解析処理
if pdf_files and df_ledger is not None:
    if st.button("🚀 爆速解析スタート！"):
        if not api_key:
            st.error("左側のサイドバーにAPIキーを入力してください。")
            st.stop()
            
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            # 1. PDFからテキストを一括抽出
            status_text.info("📄 PDFからテキストを抽出中...")
            full_text = ""
            for pdf_file in pdf_files:
                doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
                for page in doc:
                    full_text += page.get_text()
            
            # 2. ターボ設定: 5,000文字ずつに分割 (以前の約17倍の速さ)
            chunk_size = 5000
            overlap = 500 # データの泣き別れ防止用に500文字重ねる
            chunks = []
            for i in range(0, len(full_text), chunk_size - overlap):
                chunks.append(full_text[i : i + chunk_size])
            
            chunks = [c for c in chunks if len(c.strip()) > 10]
            total_chunks = len(chunks)
            
            all_ai_data = []
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            # 3. AIによる高速解析
            for i, chunk in enumerate(chunks):
                status_text.info(f"⚡ 爆速解析中... ({i+1}/{total_chunks})")
                progress_bar.progress(int(((i+1)/total_chunks)*90))
                
                prompt = f"""
                あなたは優秀な経理担当です。明細から「決済取引」のみを抽出しJSONリストで出力。
                年は「{target_year}年」として補完。返品や返金は金額をマイナス表記にすること。
                出力はJSONリストのみとし、説明文は一切不要。

                形式: [{{"date": "YYYY/MM/DD", "description": "摘要", "amount": 1000}}]

                【ユーザー定義の学習例】
                {user_examples if user_examples else "特になし"}

                ---解析対象テキスト---
                {chunk}
                """
                
                response = model.generate_content(prompt)
                res_text = response.text.strip()
                
                # マークダウン等の余計な装飾を削除
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
                time.sleep(0.1)

            # 4. データ集計と突合
            if not all_ai_data:
                st.warning("データが抽出されませんでした。")
            else:
                # 重複読みを排除
                df_ai = pd.DataFrame(all_ai_data).drop_duplicates()
                df_ai['date'] = pd.to_datetime(df_ai['date'], errors='coerce')
                df_ai = df_ai.dropna(subset=['date'])
                
                # 期間フィルタ & ソート
                mask = (df_ai['date'].dt.date >= start_date) & (df_ai['date'].dt.date <= end_date)
                df_ai = df_ai.loc[mask].sort_values('date').reset_index(drop=True)
                
                if df_ai.empty:
                    st.warning("指定された期間内にデータが見つかりませんでした。")
                else:
                    # 残高計算 (スライド式)
                    current_bal = start_balance
                    calc_balances = []
                    for _, row in df_ai.iterrows():
                        current_bal -= row['amount']
                        calc_balances.append(current_bal)
                    df_ai['計算残高'] = calc_balances
                    
                    # 突合ロジック (全セル検索)
                    status_text.info("🔍 会計データと最終照合中...")
                    ledger_values = set(df_ledger.astype(str).values.flatten())
                    
                    status_list = []
                    for _, row in df_ai.iterrows():
                        amt_str = str(row.get('amount', '')).replace(',','').replace('.0','').replace('▲','-')
                        status_list.append("✅ 済" if amt_str in ledger_values else "❌ 漏れ")
                    
                    df_ai['状況'] = status_list
                    df_ai['date'] = df_ai['date'].dt.strftime('%m/%d')
                    
                    status_text.success("✨ 解析完了！")
                    progress_bar.progress(100)
                    
                    st.metric("最終的な計算残高", f"{current_bal:,} 円")
                    st.dataframe(df_ai.style.map(
                        lambda x: 'background-color: #ffcccc; color: #900;' if x == '❌ 漏れ' else '', 
                        subset=['状況']
                    ))
            
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
