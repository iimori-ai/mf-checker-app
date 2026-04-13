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
st.info("支払額（借方）を考慮し、漏れデータも日付順に並べて完璧な残高推移を計算します。")

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
        l_debit = st.selectbox("💸 借方金額 (支払・引き落とし額)", led_cols, index=find_idx(led_cols, ["借方金額", "出金", "支払"]))
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
            
            card_dict = {}
            for _, r in df_card.iterrows():
                tid = clean_id(r[c_id])
                if tid:
                    card_dict[tid] = {
                        "date": r[c_date],
                        "desc": r[c_desc],
                        "amt": clean_amt(r[c_amt]),
                        "matched": False
                    }
            
            # --- 全データを時系列に並べるためのリスト ---
            unified_rows = []
            
            for i, row in df_res.iterrows():
                credit_val = clean_amt(row[l_credit])
                debit_val = clean_amt(row[l_debit])
                orig_bal_val = clean_amt(row[l_orig_bal])
                tid = clean_id(row[l_id])
                date_dt = row["_date_dt"]
                
                actual_card_amt = 0
                status = "-"
                
                if credit_val > 0:
                    if tid and tid in card_dict:
                        card_dict[tid]["matched"] = True
                        actual_card_amt = card_dict[tid]["amt"]
                        if credit_val == actual_card_amt:
                            status = "✅ 済"
                        else:
                            status = "⚠️ 差異あり"
                    else:
                        status = "❓ 元データなし"
                        actual_card_amt = 0 
                elif debit_val > 0:
                    status = "🏦 支払"
                    actual_card_amt = 0
                else:
                    status = "-"
                    
                unified_rows.append({
                    "_sort_date": date_dt,
                    "_is_ledger": True,
                    "_orig_idx": i,
                    "取引No": tid,
                    l_date: row[l_date],
                    l_desc: row[l_desc],
                    l_debit: debit_val,
                    l_credit: credit_val,
                    "明細突合": status,
                    "帳簿残高": orig_bal_val,
                    "_actual_amt": actual_card_amt
                })

            for tid, data in card_dict.items():
                if not data["matched"]:
                    unified_rows.append({
                        "_sort_date": pd.to_datetime(data["date"], errors="coerce"),
                        "_is_ledger": False,
                        "_orig_idx": 999999,
                        "取引No": tid,
                        l_date: data["date"],
                        l_desc: data["desc"],
                        l_debit: 0,
                        l_credit: data["amt"],
                        "明細突合": "❌ 漏れ",
                        "帳簿残高": None,
                        "_actual_amt": data["amt"]
                    })
            
            def get_sort_key(x):
                ts = x["_sort_date"].timestamp() if pd.notnull(x["_sort_date"]) else float('inf')
                return (ts, 0 if x["_is_ledger"] else 1, x["_orig_idx"])
                
            unified_rows.sort(key=get_sort_key)
            
            # --- 残高計算 ---
            current_bal = start_balance
            for r in unified_rows:
                current_bal = current_bal + r["_actual_amt"] - r[l_debit]
                r["計算残高"] = current_bal
                if r["_is_ledger"]:
                    r["残高照合"] = "✅ 一致" if r["帳簿残高"] == current_bal else "❌ 不一致"
                else:
                    r["残高照合"] = "-"
                    
            df_final = pd.DataFrame(unified_rows)
            final_cols = ["取引No", l_date, l_desc, l_debit, l_credit, "明細突合", "帳簿残高", "計算残高", "残高照合"]
            df_final = df_final[final_cols]
            
            st.success("✨ 照合完了。時系列に沿って計算残高を出力しました。")
            
            # --- サマリー ---
            missing_count = len([r for r in unified_rows if r["明細突合"] == "❌ 漏れ"])
            not_found_count = len([r for r in unified_rows if r["明細突合"] == "❓ 元データなし"])
            diff_count = len([r for r in unified_rows if r["明細突合"] == "⚠️ 差異あり"])
            
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("最終計算残高", f"{current_bal:,} 円")
            m2.metric("❌ 漏れ (会計未登録)", f"{missing_count} 件")
            m3.metric("❓ 元データなし", f"{not_found_count} 件")
            m4.metric("⚠️ 差異あり", f"{diff_count} 件")
            
            st.divider()
            
            # --- 💡 フィルター＆コピー機能 ---
            st.subheader("🔍 結果の絞り込み ＆ 取引No一括コピー")
            
            # ステータスの選択リストを作成
            all_statuses = df_final["明細突合"].unique().tolist()
            selected_statuses = st.multiselect(
                "表示するステータスを選択してください（❌や⚠️だけに絞り込めます）",
                all_statuses,
                default=all_statuses # 最初はすべて選択された状態
            )
            
            # フィルターを適用
            df_filtered = df_final[df_final["明細突合"].isin(selected_statuses)].copy()
            
            # フィルターされたデータから取引Noを抽出 (空白を除外)
            tx_ids = [str(tid) for tid in df_filtered["取引No"] if str(tid).strip() != "" and str(tid).strip() != "nan"]
            tx_ids_str = "\n".join(tx_ids)
            
            col_f1, col_f2 = st.columns([3, 1])
            with col_f1:
                st.write(f"**表示件数: {len(df_filtered)} 件**")
            with col_f2:
                with st.expander("📋 表示中の取引Noを一括コピー"):
                    if tx_ids_str:
                        st.caption("右上のアイコンをクリックでコピーできます↓")
                        st.code(tx_ids_str, language="text")
                    else:
                        st.write("コピーできる取引Noがありません。")

            # --- テーブル描画 ---
            def format_bal(val):
                if pd.isna(val) or val is None or val == "-": return "-"
                if isinstance(val, (int, float)) and not math.isnan(val):
                    return f"{int(val):,}"
                return val
                
            df_filtered["帳簿残高"] = df_filtered["帳簿残高"].apply(format_bal)
            df_filtered["計算残高"] = df_filtered["計算残高"].apply(format_bal)

            st.dataframe(
                df_filtered.style.map(
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
            
            # ダウンロードもフィルター後のデータを対象にする
            csv_bytes = df_filtered.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 表示中の結果をダウンロード", io.BytesIO(csv_bytes), "突合結果_絞り込み.csv")
            
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")

elif file_ledger or file_card:
    st.warning("両方のファイルをアップロードしてください。")
