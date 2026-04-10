import streamlit as st
import pandas as pd
import google.generativeai as genai
import fitz 
import json
import time

# --- 🔐 簡易パスワード設定 ---
def check_password():
    """パスワードが正しいかチェックする関数"""
    if "password_correct" not in st.session_state:
        # 初回はパスワード入力画面を表示
        st.title("認証が必要です")
        password = st.text_input("合言葉を入力してください", type="password")
        if st.button("ログイン"):
            if password == "your_secret_password": # 👈 ここに好きなパスワードを設定
                st.session_state["password_correct"] = True
                st.rerun() # 画面を再読み込みしてツールを表示
            else:
                st.error("パスワードが違います")
        return False
    return True

# パスワードが通らなかったら、ここでプログラムを止める
if not check_password():
    st.stop()

# --- 🚀 これ以降に元のプログラム（タイトル表示など）が続く ---
st.title("MF会計 × クレカ明細 突合ツール")
# (以下、これまでのコードをそのまま続ける)
csv_file = st.file_uploader("総勘定元帳 (CSV)", type=["csv"])
pdf_file = st.file_uploader("クレカ明細 (PDF)", type=["pdf"])

df_mf = None
if csv_file is not None:
    try:
        df_mf = pd.read_csv(csv_file, encoding="shift_jis")
        st.success("CSV準備完了")
    except Exception as e:
        st.error(f"CSVエラー: {e}")

if pdf_file is not None:
    try:
        doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
            
        st.success(f"PDF準備完了 (総文字数: {len(text)}文字)")
        
        if api_key and df_mf is not None:
            if st.button("⚡ 本番：AI解析 ＆ 突合スタート！"):
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                try:
                    status_text.info("【10%】 PDFのデータを整理しています...")
                    progress_bar.progress(10)
                    time.sleep(0.5) 
                    
                    # ★ メッセージを実態に合わせて「1分〜5分」に修正しました ★
                    status_text.info("【30%】 GoogleのAIに解析を依頼しています...（ここで1分〜5分ほどかかります）")
                    progress_bar.progress(30)
                    
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    
                    prompt = f"""
                    以下のテキストはクレジットカードの明細です。
                    データから「利用日(YYYY/MM/DD)」「摘要」「金額(数値のみ)」を抽出し、以下のJSON配列形式のみを出力してください。
                    ※ ```json などのマークダウン記号や説明文は一切含めず、純粋なJSONテキストだけを返してください。

                    [
                      {{"date": "2026/04/01", "description": "〇〇商店", "amount": 1500}},
                      {{"date": "2026/04/03", "description": "アマゾン", "amount": 4200}}
                    ]

                    ---抽出元テキスト---
                    {text}
                    """
                    
                    safety_settings = [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                    ]
                    
                    response = model.generate_content(prompt, safety_settings=safety_settings)
                    
                    status_text.info("【80%】 AIからデータを受信しました！表データに変換しています...")
                    progress_bar.progress(80)
                    
                    raw_json = response.text.strip()
                    if raw_json.startswith("```json"):
                        raw_json = raw_json[7:]
                    if raw_json.startswith("```"):
                        raw_json = raw_json[3:]
                    if raw_json.endswith("```"):
                        raw_json = raw_json[:-3]
                    raw_json = raw_json.strip()
                    
                    try:
                        ai_data = json.loads(raw_json)
                        df_ai = pd.DataFrame(ai_data)
                        
                        status_text.info("【90%】 マネーフォワードのデータと突合（マッチング）しています...")
                        progress_bar.progress(90)
                        
                        status_list = []
                        mf_all_values = set(df_mf.astype(str).values.flatten())
                        
                        for _, row in df_ai.iterrows():
                            ai_amount = str(row['amount']).replace(',', '')
                            if ai_amount in mf_all_values:
                                status_list.append("✅ 登録済")
                            else:
                                status_list.append("❌ 連携漏れ・要確認")
                        
                        df_ai['MF登録状況'] = status_list
                        
                        status_text.success("【100%】 全ての処理が完了しました！")
                        progress_bar.progress(100)
                        
                        st.write("### 🔍 突合結果")
                        st.dataframe(
                            df_ai.style.map(
                                lambda x: 'background-color: #ffcccc; color: #900;' if '❌' in str(x) else '', 
                                subset=['MF登録状況']
                            )
                        )
                        
                    except json.JSONDecodeError:
                        st.error("AIが正しいJSON形式で返してくれませんでした。以下のデータを確認してください。")
                        st.code(raw_json)
                        
                except Exception as parse_error:
                    status_text.error("処理中にエラーが発生しました。")
                    st.error(f"詳細エラー: {parse_error}")
    except Exception as e:
        st.error(f"エラーが発生しました: {e}")