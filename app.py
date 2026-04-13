import streamlit as st
import pandas as pd
import io
from datetime import datetime, date

# --- 🔐 1. 認証ゲート ---
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

# --- 🚀 2. メインUI ---
st.title("会計ソフト主導 ⚡ 爆速CSV突合ツール")
st.info("会計ソフトのCSVの順番を維持したまま、カード明細と照合し残高を計算します。")

def load_csv(file):
    if file is not None:
        for enc in ["utf-8-sig", "shift_jis", "cp932"]:
            try:
                file.seek(0)
                return pd.read_csv(file, encoding=enc)
            except:
                continue
    return None

def clean_amt(val):
    try:
        v_str = str(val).replace(',', '').replace('¥', '').replace(' ', '').replace('▲', '-')
        if pd.isna(val) or v_str == '' or v_str == 'nan':
            return 0
        return int(float(v_str))
    except:
        return 0

# --- 📁 ファイルアップロード ---
st.subheader("📁 1. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1:
    csv_ledger_file = st.file_uploader("会計ソフトCSV (マネフォ・freee等)", type=["csv"], key="ledger")
with col2:
    csv_card_file = st.file_uploader("クレカ明細CSV (カード会社)", type=["csv"], key="card")

df_ledger_raw = load_csv(csv_ledger_file)
df_card_raw = load_csv(csv_card_file)

if df_ledger_raw is not None and df_card_raw is not None:
    st.markdown("---")
    
    # 3. 列の設定
    st.subheader("⚙️ 2. 列のマッピング設定")
    
    c_led, c_crd = st.columns(2)
    
    with c_led:
        st.write("**会計ソフト側**")
        led_cols = df_ledger_raw.columns.tolist()
        l_date = st.selectbox("📅 日付", led_cols, index=0)
        l_desc = st.selectbox("📝 摘要", led_cols, index=min(1, len(led_cols)-1))
        # マネフォやfreeeの「貸方(購入)」と「借方(支払)」を選択
        l_credit = st.selectbox("💰 貸方金額 (利用額)", led_cols, index=min(2, len(led_cols)-1))
        l_debit = st.selectbox("💸 借方金額 (引き落とし額)", led_cols, index=min(3, len(led_cols)-1))

    with c_crd:
        st.write("**カード明細側**")
        crd_cols = df_card_raw.columns.tolist()
        c_amt = st.selectbox("💰 金額の列", crd_cols, index=min(1, len(crd_cols)-1))

    st.markdown("---")
    st.subheader("🗓️ 3. 初期残高")
    start_balance = st.number_input("開始時点の未払金残高 (期首残高)", value=0)

    if st.button("🚀 突合 ＆ 残高計算スタート！"):
        try:
            # --- 処理開始 ---
            # 会計ソフト側のデータ (順番を維持)
            df_res = df_ledger_raw.copy()
            
            # 数値変換
            df_res["_credit"] = df_res[l_credit].apply(clean_amt)
            df_res["_debit"] = df_res[l_debit].apply(clean_amt)
            
            # カード明細側の金額をセット化 (突合用)
            card_amounts = set(df_card_raw[c_amt].apply(lambda x: str(clean_amt(x))))
            
            # 残高計算と突合フラグ
            current_bal = start_balance
            balances = []
            matches = []
            
            for _, row in df_res.iterrows():
                # 残高推移: 前の残高 + 今回利用額(貸方) - 引き落とし額(借方)
                current_bal = current_bal + row["_credit"] - row["_debit"]
                balances.append(current_bal)
                
                # 突合: 利用額(貸方)がある行のみカード明細と照合
                if row["_credit"] > 0:
                    amt_str = str(row["_credit"])
                    matches.append("✅ 済" if amt_str in card_amounts else "❌ 漏れ")
                elif row["_debit"] > 0:
                    matches.append("🏦 支払")
                else:
                    matches.append("-")
            
            df_res["突合状況"] = matches
            df_res["計算残高"] = balances
            
            # 表示する列を絞る
            final_cols = [l_date, l_desc, l_credit, l_debit, "突合状況", "計算残高"]
            df_display = df_res[final_cols]
            
            st.success("✨ 完了しました。会計ソフトの順番通りに表示しています。")
            
            # メトリック表示
            m1, m2, m3 = st.columns(3)
            m1.metric("最終未払残高", f"{current_bal:,} 円")
            m2.metric("総件数", f"{len(df_display)} 件")
            m3.metric("未連携(❌)数", f"{len(df_res[df_res['突合状況'] == '❌ 漏れ'])} 件")
            
            # テーブル表示
            st.dataframe(
                df_display.style.map(
                    lambda x: "background-color: #ffcccc; color: #900;" if x == "❌ 漏れ" else "",
                    subset=["突合状況"]
                ).map(
                    lambda x: "background-color: #e1f5fe;" if x == "🏦 支払" else "",
                    subset=["突合状況"]
                ),
                use_container_width=True
            )
            
            # CSVダウンロード
            csv_bytes = df_display.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 結果をダウンロード", io.BytesIO(csv_bytes), "突合結果.csv", "text/csv")
            
        except Exception as e:
            st.error(f"エラー: {e}")

elif csv_ledger_file or csv_card_file:
    st.warning("両方のCSVファイルをアップロードしてください。")
