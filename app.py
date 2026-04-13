import streamlit as st
import pandas as pd
import io
from datetime import datetime, date
import math

# 💡 画面全体を広く使う「ワイドモード」
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
st.title("会計ソフト主導 ⚡ 爆速ファイル突合ツール (取引No照合版)")
st.info("取引Noをキーにして照合します。「漏れ」「元データなし」「差異あり」を厳密に判定します。")

# --- 🛠️ 関数群 ---
def load_file(file):
    if file is not None:
        filename = file.name.lower()
        if filename.endswith(('.xlsx', '.xls')):
            try:
                return pd.read_excel(file)
            except Exception as e:
                st.error(f"Excelの読み取りエラー: {e}")
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

def clean_id(val):
    """取引Noのフォーマットを統一（.0の削除や空白除去）"""
    if pd.isna(val): return ""
    v_str = str(val).strip()
    if v_str.endswith('.0'): v_str = v_str[:-2]
    return v_str if v_str != 'nan' else ""

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
        l_id = st.selectbox("🔑 取引No列", led_cols, index=find_idx(led_cols, ["取引No", "ID", "伝票番号", "番号"]))
        l_date = st.selectbox("📅 日付列", led_cols, index=find_idx(led_cols, ["日付", "年月日", "取引日"]))
        l_desc = st.selectbox("📝 摘要列", led_cols, index=find_idx(led_cols, ["内容", "摘要", "取引内容"]))
        l_debit = st.selectbox("💸 借方金額 (支払額)", led_cols, index=find_idx(led_cols, ["借方金額", "出金", "支払"]))
        l_credit = st.selectbox("💰 貸方金額 (利用額)", led_cols, index=find_idx(led_cols, ["貸方金額", "入金", "利用"]))
        l_orig_bal = st.selectbox("🏛️ 帳簿残高列", led_cols, index=find_idx(led_cols, ["残高"]))

    with c_crd:
        st.write("**カード明細側**")
        st.caption("※「漏れ」データを発見した際に表示するため、日付や摘要も指定してください。")
        c_id = st.selectbox("🔑 取引No列 ", crd_cols, index=find_idx(crd_cols, ["取引No", "ID", "伝票番号", "番号"]))
        c_date = st.selectbox("📅 日付列 ", crd_cols, index=find_idx(crd_cols, ["日付", "年月日", "利用日"]))
        c_desc = st.selectbox("📝 摘要列 ", crd_cols, index=find_idx(crd_cols, ["内容", "摘要", "店名", "利用店"]))
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

    if st.button("🚀 照合 ＆ 残高計算スタート！"):
        try:
            # --- 会計側のデータ準備 ---
            df_res = df_ledger_raw.copy()
            df_res["_date_dt"] = pd.to_datetime(df_res[l_date], errors="coerce")
            
            mask_led = (df_res["_date_dt"].dt.date >= start_date) & (df_res["_date_dt"].dt.date <= end_date)
            df_res = df_res.loc[mask_led].copy()
            
            if df_res.empty:
                st.warning("指定された期間内に会計データがありません。")
                st.stop()
                
            # --- カード側のデータ準備 (辞書化) ---
            df_card = df_card_raw.copy()
            df_card["_date_dt"] = pd.to_datetime(df_card[c_date], errors="coerce")
            mask_crd = (df_card["_date_dt"].dt.date >= start_date) & (df_card["_date_dt"].dt.date <= end_date)
            df_card = df_card.loc[mask_crd].copy()
            
            # 取引Noをキーにしたカード明細の辞書を作成
            card_dict = {}
            for _, r in df_card.iterrows():
                tid = clean_id(r[c_id])
                if tid:
                    card_dict[tid] = {
                        "date": r[c_date],
                        "desc": r[c_desc],
                        "amt": clean_amt(r[c_amt]),
                        "matched": False # 突合チェック用フラグ
                    }
            
            # --- メイン突合ループ ---
            current_bal = start_balance
            calc_balances = []
            status_list = []
            match_checks = []
            
            for _, row in df_res.iterrows():
                credit_val = clean_amt(row[l_credit])
                debit_val = clean_amt(row[l_debit])
                orig_bal_val = clean_amt(row[l_orig_bal])
                tid = clean_id(row[l_id])
                
                # 1. 残高計算
                current_bal = current_bal + credit_val - debit_val
                calc_balances.append(current_bal)
                
                # 2. 取引Noベースの突合
                if tid and credit_val > 0:
                    if tid in card_dict:
                        card_dict[tid]["matched"] = True # カード側のフラグを立てる
                        if credit_val == card_dict[tid]["amt"]:
                            status_list.append("✅ 済")
                        else:
                            status_list.append("⚠️ 差異あり")
                    else:
                        status_list.append("❓ 元データなし")
                elif debit_val > 0:
                    status_list.append("🏦 支払")
                elif credit_val > 0:
                    # 取引Noが空欄の利用
                    status_list.append("❓ 元データなし")
                else:
                    status_list.append("-")
                
                # 3. 残高照合
                if orig_bal_val == current_bal:
                    match_checks.append("✅ 一致")
                else:
                    match_checks.append("❌ 不一致")
            
            # 会計ソフト側の結果を反映
            df_res["取引No"] = df_res[l_id].apply(clean_id)
            df_res["明細突合"] = status_list
            df_res["計算残高"] = calc_balances
            df_res["残高照合"] = match_checks
            df_res = df_res.rename(columns={l_orig_bal: "帳簿残高"})
            
            # 表示用の列
            final_cols = ["取引No", l_date, l_desc, l_debit, l_credit, "明細突合", "帳簿残高", "計算残高", "残高照合"]
            df_final = df_res[final_cols].copy()
            
            # --- ❌ 漏れ（カードにあるが会計にない）の抽出 ---
            missing_rows = []
            for tid, data in card_dict.items():
                if not data["matched"]:
                    missing_rows.append({
                        "取引No": tid,
                        l_date: data["date"],
                        l_desc: data["desc"],
                        l_debit: 0,
                        l_credit: data["amt"],
                        "明細突合": "❌ 漏れ",
                        "帳簿残高": "-",
                        "計算残高": "-",
                        "残高照合": "-"
                    })
            
            # 漏れ行を表の末尾に追加
            missing_count = len(missing_rows)
            if missing_count > 0:
                df_missing = pd.DataFrame(missing_rows)
                df_final = pd.concat([df_final, df_missing], ignore_index=True)
            
            st.success("✨ 照合完了")
            
            # サマリー
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("最終計算残高", f"{current_bal:,} 円")
            m2.metric("❌ 漏れ (会計未登録)", f"{missing_count} 件")
            m3.metric("❓ 元データなし", f"{status_list.count('❓ 元データなし')} 件")
            m4.metric("⚠️ 差異あり", f"{status_list.count('⚠️ 差異あり')} 件")
            
            # 残高をカンマ区切りの文字列にフォーマット（ "-" と混在してもエラーにならないように処理）
            def format_bal(val):
                if isinstance(val, (int, float)) and not math.isnan(val):
                    return f"{int(val):,}"
                return val
                
            df_final["帳簿残高"] = df_final["帳簿残高"].apply(format_bal)
            df_final["計算残高"] = df_final["計算残高"].apply(format_bal)

            # テーブル描画
            st.dataframe(
                df_final.style.map(
                    lambda x: "background-color: #ffcccc; color: #900;" if x in ["❌ 漏れ", "❌ 不一致"] else "",
                    subset=["明細突合", "残高照合"]
                ).map(
                    lambda x: "background-color: #fff3e0; color: #e65100;" if x == "⚠️ 差異あり" else "",
                    subset=["明細突合"]
                ).map(
                    lambda x: "background-color: #f3e5f5; color: #6a1b9a;" if x == "❓ 元データなし" else "",
                    subset=["明細突合"]
                ).map(
                    lambda x: "background-color: #e3f2fd;" if x == "🏦 支払" else "",
                    subset=["明細突合"]
                ),
                use_container_width=True
            )
            
            csv_bytes = df_final.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 結果をダウンロード", io.BytesIO(csv_bytes), "突合結果.csv")
            
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")

elif file_ledger or file_card:
    st.warning("両方のファイルをアップロードしてください。")
