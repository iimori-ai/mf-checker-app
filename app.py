import streamlit as st
import pandas as pd
import google.generativeai as genai
import fitz  # PyMuPDF
import json
from datetime import datetime, date
import time
import math

# --- 🔐 1. 認証ゲート ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 認証が必要です")
    # 合言葉：351835（自由に変更してください）
    password = st.text_input("合言葉を入力してください", type="password")
    if st.button("ログイン"):
        if password == "351835": 
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("合言葉が正しくありません")
    st.stop()

# --- 🚀 2. メインUI ---
st.title("会計ソフト × クレカ明細 突合・学習型ツール ⚡ 2.5 Flash版")

with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini APIキー", type="password")
    st.divider()
    st.header("🎓 AIへの学習（お手本）")
    user_examples = st.text_area(
        "学習用サンプル", 
        placeholder="例: 特定の店名はこう読み替えて、等の指示をここに書きます。",
        height=150
    )

st.subheader("🔑 1. 初期設定")
this_year = datetime.now().year
target_year = st.selectbox("対象年", [this_year, this_year - 1, this_year - 2], index=0)

st.subheader("🗓️ 2. 期間と残高の設定")
col_start, col_end, col_bal = st.columns(3)
with col_start:
    start_date = st.date_input("開始日", value=date(target_year, 1, 1))
with col_end:
    end_date = st.date_input("終了日", value=date(target_year, 12, 31))
with col_bal:
    start_balance = st.number_input("期首残高（開始日の前日時点）", value=0)

st.subheader("📁 3. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1:
    csv_file = st.file_uploader("会計ソフトCSV (MF・freee等)", type=["csv"])
with col2:
    pdf_files = st.file_uploader("クレカ明細PDF (複数可)", type=["pdf"], accept_multiple_files=True)

# 会計データ読み込み (自動判別)
df_ledger = None
if csv_file:
    for enc in ["utf-8-sig", "shift_jis", "cp932"]:
        try:
            csv_file.seek(0)
            df_ledger = pd.read_csv(csv_file, encoding=enc)
            st.success(f"✅ 会計データ読み込み成功")
            break
        except:
            continue

# --- 🧠 3. 解析・突合ロジック ---
if pdf_files and df_ledger is not None:
    if st.button("🚀 10%ずつ進む！爆速解析スタート！"):
        if not api_key:
            st.error("左のサイドバーにAPIキーを入れてください。")
            st.stop()
            
        try:
            # Step A: 全PDFからテキストを抽出
            pages_text = []
            for pdf in pdf_files:
                doc = fitz.open(stream=pdf.read(), filetype="pdf")
                for page in doc:
                    t = page.get_text().strip()
                    if t: pages_text.append(t)
                doc.close()
            
            if not pages_text:
                st.warning("PDFから文字を抽出できませんでした。")
                st.stop()

            # 💡 改善：全ページを正確に「10の束」に分ける
            num_steps = 10
            total_pages = len(pages_text)
            step_size = total_pages / num_steps
            
            chunks = []
            for i in range(num_steps):
                start_idx = int(i * step_size)
                end_idx = int((i + 1) * step_size)
                # 最後のステップは余ったページをすべて含む
                if i == num_steps - 1:
                    chunk = pages_text[start_idx:]
                else:
                    chunk = pages_text[start_idx:end_idx]
                if chunk:
                    chunks.append(chunk)

            genai.configure(api_key=api_key)
            # 指定通り 2.5-flash モデルを使用
            model = genai.GenerativeModel("gemini-2.5-flash")
            
            all_ai_data = []
            st.write("---")
            status_text = st.empty()
            progress_bar = st.progress(0)
            
            # Step B: AI解析のループ (必ず最大10回)
            for i, chunk in enumerate(chunks):
                current_step = i + 1
                current_pct = current_step * 10
                status_text.markdown(f"### 🤖 解析中: ステップ {current_step} / 10 ({current_pct}%)")
                
                chunk_text = "\n".join(chunk)
                prompt = f"""
                明細から決済取引のみを抽出しJSONリストで出力せよ。
                年は{target_year}年補完。返品は金額マイナス。
                形式: [{{"date": "YYYY/MM/DD", "description": "摘要", "amount": 1000}}]
                【学習例】: {user_examples}
                ---対象テキスト---
                {chunk_text}
                """
                
                response = model.generate_content(prompt)
                res_text = response.text.strip()
                
                if "```json" in res_text:
                    res_text = res_text.split("```json")[1].split("```")[0]
                elif "```" in res_text:
                    res_text = res_text.split("```")[1].split("```")[0]
                
                try:
                    data = json.loads(res_text.strip())
                    if isinstance(data, list): all_ai_data.extend(data)
                except: pass
                
                # 10%ずつ正確に進む
                progress_bar.progress(current_pct / 100)
                time.sleep(0.1)

            # Step C: データの整形・突合
            if not all_ai_data:
                st.warning("取引が見つかりませんでした。")
            else:
                df_ai = pd.DataFrame(all_ai_data).drop_duplicates()
                df_ai["date"] = pd.to_datetime(df_ai["date"], errors="coerce")
                df_ai = df_ai.dropna(subset=["date"])
                
                mask = (df_ai["date"].dt.date >= start_date) & (df_ai["date"].dt.date <= end_date)
                df_ai = df_ai.loc[mask].sort_values("date").reset_index(drop=True)
                
                # 残高計算
                df_ai["計算残高"] = start_balance - df_ai["amount"].cumsum()
                
                # 突合
                ledger_values = set(df_ledger.astype(str).values.flatten())
                def check_matching(amt):
                    try:
                        # 金額の表記揺れ（カンマや小数点）を吸収
                        a_str = str(int(float(str(amt).replace(',',''))))
                        return "✅ 済" if a_str in ledger_values else "❌ 漏れ"
                    except: return "❓"
                
                df_ai["状況"] = df_ai["amount"].apply(check_matching)
                df_ai["date"] = df_ai["date"].dt.strftime("%m/%d")
                
                status_text.success(f"✨ 全10ステップ完了！結果を表示します。")
                st.divider()
                
                m1, m2 = st.columns(2)
                if not df_ai.empty:
                    m1.metric("最終計算残高", f"{int(df_ai['計算残高'].iloc[-1]):,} 円")
                m2.metric("抽出件数", f"{len(df_ai)} 件")
                
                st.dataframe(
                    df_ai.style.map(lambda x: "background-color: #ffcccc; color: #900;" if x == "❌ 漏れ" else "", subset=["状況"]), 
                    use_container_width=True
                )
                
        except Exception as e:
            st.error(f"エラー: {e}")
