import streamlit as st
import pandas as pd
import io
from datetime import datetime, date

# 💡 ここで画面全体を広く使う「ワイドモード」に設定しています
st.set_page_config(page_title="会計・クレカ突合ツール", layout="wide")

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
st.info("貸方の隣に突合状況を、帳簿残高の隣に計算結果との一致チェックを追加しました。")

# --- 🛠️ 関数群 ---
def load_file(file):
    if file is not None:
        filename = file.name.lower()
        if filename.endswith(('.xlsx', '.xls')):
            try:
                return pd.read_excel(file)
            except Exception as e:
                st.error(f"Excelの読み取りに失敗しました: {e}")
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

def find_idx(cols, keywords):
    for i, col in enumerate(cols):
        if any(k in str(col) for k in keywords):
            return i
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
    
    # 2. 列の設定
    st.subheader("⚙️ 2. 列のマッピング設定")
    led_cols = df_ledger_raw.columns.tolist()
    crd_cols = df_card_raw.columns.tolist()
    
    c_led, c_crd = st.columns(2)
    with c_led:
        st.write("**会計ソフト側 (MF等)**")
        l_date = st.selectbox("📅 日付列", led_cols, index=find_idx(led_cols, ["日付", "年月日", "取引日"]))
        l_desc = st.selectbox("📝 摘要列", led_cols, index=find_idx(led_cols, ["内容", "摘要", "取引内容"]))
        l_debit = st.selectbox("💸 借方金額 (支払額)", led_cols, index=find_idx(led_cols, ["借方金額", "出金", "支払"]))
        l_credit = st.selectbox("💰 貸方金額 (利用額)", led_cols, index=find_idx(led_cols, ["貸方金額", "入金", "利用"]))
        l_orig_bal = st.selectbox("🏛️ 帳簿残高列", led_cols, index=find_idx(led_cols, ["残高"]))

    with c_crd:
        st.write("**カード明細側**")
        c_amt = st.selectbox("💰 金額の列", crd_cols, index=find_idx(crd_cols, ["金額", "利用額", "支払金額"]))

    st.markdown("---")
    st.subheader("🗓️ 3. 期間と初期残高の設定")
    this_year = datetime.now().year
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        start_date = st.date_input("開始日", value=date(this_year, 1, 1))
    with col_s2:
        end_date = st.date_input("終了日", value=date(this_year, 12, 31))
    with col_s3:
        start_balance = st.number_input("開始日の「前日」時点の残高", value=0)

    if st.button("🚀 解析スタート！"):
        try:
            df_res = df_ledger_raw.copy()
            df_res["_date_dt"] = pd.to_datetime(df_res[l_date], errors="coerce")
            
            mask = (df_res["_date_dt"].dt.date >= start_date) & (df_res["_date_dt"].dt.date <= end_date)
            df_res = df_res.loc[mask].copy()
            
            if df_res.empty:
                st.warning("指定された期間内にデータがありません。")
                st.stop()
            
            # 数値クレンジング
            df_res["_debit_val"] = df_res[l_debit].apply(clean_amt)
            df_res["_credit_val"] = df_res[l_credit].apply(clean_amt)
            df_res["_orig_bal_val"] = df_res[l_orig_bal].apply(clean_amt)
            
            card_amounts = set(df_card_raw[c_amt].apply(lambda x: str(clean_amt(x))))
            
            current_bal = start_balance
            calc_balances = []
            status_list = []
            match_checks = []
            
            for _, row in df_res.iterrows():
                # 残高計算
                current_bal = current_bal + row["_credit_val"] - row["_debit_val"]
                calc_balances.append(current_bal)
                
                # 1. 突合（カード明細にあるか）
                if row["_credit_val"] > 0:
                    status_list.append("✅ 済" if str(row["_credit_val"]) in card_amounts else "❌ 漏れ")
                elif row["_debit_val"] > 0:
                    status_list.append("🏦 支払")
                else:
                    status_list.append("-")
                
                # 2. 残高照合（帳簿残高と計算残高が一致するか）
                if row["_orig_bal_val"] == current_bal:
                    match_checks.append("✅ 一致")
                else:
                    match_checks.append("❌ 不一致")
            
            df_res["明細突合"] = status_list
            df_res["計算残高"] = calc_balances
            df_res["残高照合"] = match_checks
            
            # 列名をわかりやすく「帳簿残高」にリネーム
            df_res = df_res.rename(columns={l_orig_bal: "帳簿残高"})
            
            # --- 🚀 レイアウト指定 ---
            # 日付 | 摘要 | 借方 | 貸方 | 明細突合 | 帳簿残高 | 計算残高 | 残高照合
            final_cols = [l_date, l_desc, l_debit, l_credit, "明細突合", "帳簿残高", "計算残高", "残高照合"]
            df_final = df_res[final_cols].copy()
            
            st.success("✨ 解析完了")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("最終計算残高", f"{current_bal:,} 円")
            m2.metric("明細漏れ", f"{status_list.count('❌ 漏れ')} 件")
            m3.metric("残高不一致", f"{match_checks.count('❌ 不一致')} 件")
            
            # テーブル描画
            st.dataframe(
                df_final.style.map(
                    lambda x: "background-color: #ffcccc; color: #900;" if "❌" in str(x) else "",
                    subset=["明細突合", "残高照合"]
                ).map(
                    lambda x: "background-color: #e3f2fd;" if x == "🏦 支払" else "",
                    subset=["明細突合"]
                ).format({"帳簿残高": "{:,}", "計算残高": "{:,}"}),
                use_container_width=True
            )
            
            csv_bytes = df_final.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 結果をダウンロード", io.BytesIO(csv_bytes), "突合結果.csv")
            
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")

elif file_ledger or file_card:
    st.warning("両方のファイルをアップロードしてください。")
