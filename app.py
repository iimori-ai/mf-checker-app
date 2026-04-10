import streamlit as st
import pandas as pd
import google.generativeai as genai
import fitz  # PyMuPDF
import json
from datetime import datetime, date
import time

# --- 🔐 1. 認証ゲート ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 認証が必要です")
    # 合言葉：351835
    password = st.text_input("合言葉を入力してください", type="password")
    if st.button("ログイン"):
        if password == "351835": 
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("合言葉が正しくありません")
    st.stop()

# --- 🚀 2. メインUI ---
st.title("会計ソフト × クレカ明細 突合・学習型ツール ⚡")

with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("Gemini APIキー", type="password")
    st.divider()
    st.header("🎓 AIへの学習（お手本）")
    user_examples = st.text_area(
        "学習用サンプル", 
        placeholder="例: '一括払いからの変更'という行は無視して。特定の店名はこう読み替えて。",
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

# 会計データ読み込み (自動エンコード判別)
df_ledger = None
if csv_file:
    for enc in ["utf-8-sig", "shift_jis", "cp932"]:
        try:
            csv_file.seek(0)
            df_ledger = pd.read_csv(csv_file, encoding=enc)
            st.success(f"✅ 会計データ読み込み成功 ({enc})")
            break
        except:
            continue

# --- 🧠 3. 解析・突合ロジック ---
if pdf_files and df_ledger is not None:
    if st.button("🚀 解析スタート！"):
        if not api_key:
            st.error("左のサイドバーにGemini APIキーを入力してください。")
            st.stop()
            
        try:
            # Step A: PDFからテキストを抽出（ページ単位でリスト化）
            pages_text = []
            for pdf in pdf_files:
                doc = fitz.open(stream=pdf.read(), filetype="pdf")
                for page in doc:
                    t = page.get_text().strip()
                    if t:
                        pages_text.append(t)
                doc.close()
            
            # 💡 タイムアウト対策：2ページずつ小分けにしてAIに渡す（進捗バーを動かすため）
            chunk_size = 2 
            chunks = [pages_text[i:i + chunk_size] for i in range(0, len(pages_text), chunk_size)]
            total_chunks = len(chunks)
            
            if total_chunks == 0:
                st.warning("PDFから文字を抽出できませんでした。")
                st.stop()

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")
            
            all_ai_data = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Step B: AI解析のループ
            for i, chunk in enumerate(chunks):
                status_text.info(f"🤖 AIが解析中... ({i+1} / {total_chunks} ブロック)")
                
                chunk_text = "\n".join(chunk)
                prompt = f"""
                明細から決済取引（日付, 摘要, 金額）を抽出しJSONリストで出力してください。
                年は{target_year}年として補完。返品や調整金は金額をマイナス表記に。
                出力はJSONリストのみ。説明不要。
                形式: [{{"date": "YYYY/MM/DD", "description": "摘要", "amount": 1000}}]
                【学習例】: {user_examples}
                ---対象テキスト---
                {chunk_text}
                """
                
                response = model.generate_content(prompt)
                res_text = response.text.strip()
                
                # JSON部分を抽出
                if "```json" in res_text:
                    res_text = res_text.split("```json")[1].split("```")[0]
                elif "```" in res_text:
                    res_text = res_text.split("```")[1].split("```")[0]
                
                try:
                    data = json.loads(res_text.strip())
                    if isinstance(data, list):
                        all_ai_data.extend(data)
                except:
                    pass
                
                # 進捗率を更新
                progress_bar.progress((i + 1) / total_chunks)
                time.sleep(0.1)

            # Step C: データの整形・突合
            if not all_ai_data:
                st.warning("取引データが見つかりませんでした。")
            else:
                df_ai = pd.DataFrame(all_ai_data).drop_duplicates()
                df_ai["date"] = pd.to_datetime(df_ai["date"], errors="coerce")
                df_ai = df_ai.dropna(subset=["date"])
                
                # 期間フィルタ & ソート
                mask = (df_ai["date"].dt.date >= start_date) & (df_ai["date"].dt.date <= end_date)
                df_ai = df_ai.loc[mask].sort_values("date").reset_index(drop=True)
                
                # 残高計算
                df_ai["計算残高"] = start_balance - df_ai["amount"].cumsum()
                
                # 突合処理
                ledger_values = set(df_ledger.astype(str).values.flatten())
                def check_matching(amt):
                    # コンマや小数点を無視して比較
                    try:
                        a_str = str(int(float(str(amt).replace(',',''))))
                        return "✅ 済" if a_str in ledger_values else "❌ 漏れ"
                    except:
                        return "❓ 不明"
                
                df_ai["状況"] = df_ai["amount"].apply(check_matching)
                
                # 表示用に整形
                df_ai["date"] = df_ai["date"].dt.strftime("%m/%d")
                status_text.success("✨ 解析・突合が完了しました！")
                
                # 結果表示
                st.divider()
                m1, m2 = st.columns(2)
                if not df_ai.empty:
                    m1.metric("最終計算残高", f"{int(df_ai['計算残高'].iloc[-1]):,} 円")
                m2.metric("抽出件数", f"{len(df_ai)} 件")
                
                st.dataframe(
                    df_ai.style.map(
                        lambda x: "background-color: #ffcccc; color: #900;" if x == "❌ 漏れ" else "",
                        subset=["状況"]
                    ),
                    use_container_width=True
                )
                
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
