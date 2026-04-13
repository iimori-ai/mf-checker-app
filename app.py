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
st.title("会計ソフト主導 ⚡ 爆速ファイル突合ツール")
st.info("入力した期首残高から、利用額と引き落とし額を一行ずつ計算して「正しい残高」を表示します。")

# 読み込み関数
def load_file(file):
    if file is not None:
        filename = file.name.lower()
        if filename.endswith(('.xlsx', '.xls')):
            try:
                return pd.read_excel(file)
            except Exception as e:
                st.error(f"Excelの読み込みエラー: {e}")
                return None
        else:
            for enc in ["utf-8-sig", "shift_jis", "cp932"]:
                try:
                    file.seek(0)
                    return pd.read_csv(file, encoding=enc)
                except:
                    continue
    return None

def clean_amt(val):
    try:
        if pd.isna(val): return 0
        v_str = str(val).replace(',', '').replace('¥', '').replace(' ', '').replace('▲', '-')
        if v_str == '' or v_str == 'nan': return 0
        return int(float(v_str))
    except:
        return 0

# --- 📁 1. ファイルアップロード ---
st.subheader("📁 1. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1:
    file_ledger = st.file_uploader("会計ソフト (CSV / Excel)", type=["csv", "xlsx", "xls"], key="ledger")
with col2:
    file_card = st.file_uploader("クレカ明細 (CSV / Excel)", type=["csv", "xlsx", "xls"], key="card")

df_ledger_raw = load_file(file_ledger)
df_card_raw = load_file(file_card)

if df_ledger_raw is not None and df_card_raw is not None:
    st.markdown("---")
    
    # 2. 列の設定 (ヘッダー準拠)
    st.subheader("⚙️ 2. 列のマッピング設定")
    c_led, c_crd = st.columns(2)
    
    with c_led:
        st.write("**会計ソフト側 (MF/freee等)**")
        led_cols = df_ledger_raw.columns.tolist()
        l_date = st.selectbox("📅 日付列", led_cols, index=0)
        l_desc = st.selectbox("📝 摘要列", led_cols, index=min(1, len(led_cols)-1))
        # 簿記の標準: 借方(左)=支払・返金 / 貸方(右)=利用
        l_debit = st.selectbox("💸 借方金額 (引き落とし・支払額)", led_cols, index=min(2, len(led_cols)-1))
        l_credit = st.selectbox("💰 貸方金額 (カード利用額)", led_cols, index=min(3, len(led_cols)-1))

    with c_crd:
        st.write("**カード明細側**")
        crd_cols = df_card_raw.columns.tolist()
        c_amt = st.selectbox("💰 利用金額の列", crd_cols, index=min(1, len(crd_cols)-1))

    st.markdown("---")
    st.subheader("🗓️ 3. 期間と初期残高の設定")
    this_year = datetime.now().year
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        start_date = st.date_input("開始日", value=date(this_year, 1, 1))
    with col_s2:
        end_date = st.date_input("終了日", value=date(this_year, 12, 31))
    with col_s3:
        # ユーザーが指定した開始日の「前日時点」の未払金残高
        start_balance = st.number_input("開始日時点の残高 (未払金残高)", value=0)

    if st.button("🚀 突合 ＆ 残高計算スタート！"):
        try:
            # 会計側のデータを加工
            df_res = df_ledger_raw.copy()
            df_res["_date_dt"] = pd.to_datetime(df_res[l_date], errors="coerce")
            
            # 期間フィルタリング（順番は維持）
            mask = (df_res["_date_dt"].dt.date >= start_date) & (df_res["_date_dt"].dt.date <= end_date)
            df_res = df_res.loc[mask].copy()
            
            if df_res.empty:
                st.warning("期間内にデータがありません。")
                st.stop()
            
            # 金額のクレンジング
            df_res["_debit_val"] = df_res[l_debit].apply(clean_amt)
            df_res["_credit_val"] = df_res[l_credit].apply(clean_amt)
            
            # カード側の金額をセット化
            card_amounts = set(df_card_raw[c_amt].apply(lambda x: str(clean_amt(x))))
            
            # --- 核心：残高と突合の計算 ---
            current_bal = start_balance
            calc_balances = []
            status_list = []
            
            for _, row in df_res.iterrows():
                # 会計上の残高計算ロジック
                # 未払金勘定の場合: 残高 = 前残高 + 利用(貸方) - 支払(借方)
                current_bal = current_bal + row["_credit_val"] - row["_debit_val"]
                calc_balances.append(current_bal)
                
                # 突合ロジック
                if row["_credit_val"] > 0:
                    # 利用額がある場合、カード明細にその金額があるか
                    is_match = str(row["_credit_val"]) in card_amounts
                    status_list.append("✅ 済" if is_match else "❌ 漏れ")
                elif row["_debit_val"] > 0:
                    # 引き落とし額がある場合
                    status_list.append("🏦 支払")
                else:
                    status_list.append("-")
            
            df_res["突合状況"] = status_list
            df_res["計算残高"] = calc_balances
            
            # 結果表示用の列整理
            display_cols = [l_date, l_desc, l_debit, l_credit, "突合状況", "計算残高"]
            df_final = df_res[display_cols].copy()
            
            st.success("✨ 突合完了。会計ソフトの帳簿順に計算しました。")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("最終計算残高", f"{current_bal:,} 円")
            m2.metric("処理件数", f"{len(df_final)} 件")
            m3.metric("未連携(❌)", f"{status_list.count('❌ 漏れ')} 件")
            
            # テーブル描画
            st.dataframe(
                df_final.style.map(
                    lambda x: "background-color: #ffcccc; color: #900;" if x == "❌ 漏れ" else "",
                    subset=["突合状況"]
                ).map(
                    lambda x: "background-color: #e1f5fe;" if x == "🏦 支払" else "",
                    subset=["突合状況"]
                ).format({"計算残高": "{:,}"}),
                use_container_width=True
            )
            
            # ダウンロード
            csv_bytes = df_final.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 結果をCSVで保存", io.BytesIO(csv_bytes), f"突合結果_{start_date}.csv")
            
        except Exception as e:
            st.error(f"エラー: {e}")
