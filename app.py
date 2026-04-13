import streamlit as st
import pandas as pd
import io
from datetime import datetime, date
import math
import unicodedata

# 💡 画面全体を広く使う「ワイドモード」
st.set_page_config(page_title="会計・クレカ突合ツール", layout="wide")

# 💡 表だけの「部分更新（Fragment）」機能をセットアップ
if hasattr(st, "fragment"):
    fragment_decorator = st.fragment
elif hasattr(st, "experimental_fragment"):
    fragment_decorator = st.experimental_fragment
else:
    fragment_decorator = lambda f: f

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
st.title("会計ソフト主導 ⚡ 爆速ファイル突合ツール (完全版)")
st.info("【スクロール問題・完全解決】表のデータ更新タイミングを分けることで、画面ジャンプを完全に封じ込めました！")

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
        if pd.isna(val) or val == "" or val == "-": return 0
        if isinstance(val, (int, float)): return int(val)
        v_str = str(val).replace(',', '').replace('¥', '').replace(' ', '').replace('▲', '-')
        if v_str == '' or v_str == 'nan': return 0
        return int(float(v_str))
    except:
        return 0

def clean_id(val):
    if pd.isna(val): return ""
    v_str = unicodedata.normalize('NFKC', str(val)).strip()
    if v_str.endswith('.0'): v_str = v_str[:-2]
    return v_str if v_str != 'nan' else ""

def find_idx(cols, keywords):
    for i, col in enumerate(cols):
        if any(k in str(col) for k in keywords):
            return i
    return 0

# 計算ロジック（※2重計算のバグ修正済み）
def recalculate_balances(df, start_bal):
    curr_bal = start_bal
    new_bals = []
    new_checks = []
    
    for _, r in df.iterrows():
        status = r["明細突合"]
        debit = clean_amt(r.get("借方金額", 0))
        credit = clean_amt(r.get("貸方金額", 0))
        actual_card_amt = clean_amt(r.get("_actual_amt", 0))
        
        if status in ["✅ 済", "⚠️ 差異あり"]:
            if actual_card_amt != 0:
                curr_bal += actual_card_amt
            else:
                curr_bal += (credit - debit)
        elif status == "❌ 漏れ":
            curr_bal += actual_card_amt
        elif status == "🏦 支払":
            curr_bal -= debit
            
        new_bals.append(curr_bal)
        
        if r.get("_is_ledger", False):
            orig = clean_amt(r.get("帳簿残高", 0))
            new_checks.append("✅ 一致" if orig == curr_bal else "❌ 不一致")
        else:
            new_checks.append("-")
            
    df["計算残高"] = new_bals
    df["残高照合"] = new_checks
    return df, curr_bal

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

    # 初回実行フラグの初期化
    if "is_calculated" not in st.session_state:
        st.session_state.is_calculated = False

    if st.button("🚀 照合 ＆ 残高計算スタート！"):
        try:
            df_res = df_ledger_raw.copy()
            df_res["_date_dt"] = pd.to_datetime(df_res[l_date], errors="coerce")
            mask_led = (df_res["_date_dt"].dt.date >= start_date) & (df_res["_date_dt"].dt.date <= end_date)
            df_res = df_res.loc[mask_led].copy()
            
            df_card = df_card_raw.copy()
            df_card["_date_dt"] = pd.to_datetime(df_card[c_date], errors="coerce")
            mask_crd = (df_card["_date_dt"].dt.date >= start_date) & (df_card["_date_dt"].dt.date <= end_date)
            df_card = df_card.loc[mask_crd].copy()
            
            card_dict = {}
            for _, r in df_card.iterrows():
                tid = clean_id(r[c_id])
                if tid:
                    card_dict[tid] = {"date": r[c_date], "desc": r[c_desc], "amt": clean_amt(r[c_amt]), "matched": False}
            
            unified_rows = []
            for i, row in df_res.iterrows():
                credit_val, debit_val = clean_amt(row[l_credit]), clean_amt(row[l_debit])
                tid = clean_id(row[l_id])
                actual_card_amt, status = 0, "-"
                ledger_net = credit_val - debit_val
                
                if tid and tid in card_dict:
                    card_dict[tid]["matched"] = True
                    actual_card_amt = card_dict[tid]["amt"]
                    status = "✅ 済" if ledger_net == actual_card_amt else "⚠️ 差異あり"
                else:
                    status = "❓ 元データなし" if credit_val > 0 else "🏦 支払" if debit_val > 0 else "-"
                
                unified_rows.append({
                    "_sort_date": row["_date_dt"], "_is_ledger": True, "_orig_idx": i, "取引No": tid,
                    "日付": row[l_date], "摘要": row[l_desc], "借方金額": debit_val, "貸方金額": credit_val,
                    "明細突合": status, "帳簿残高": clean_amt(row[l_orig_bal]), "_actual_amt": actual_card_amt
                })

            for tid, data in card_dict.items():
                if not data["matched"]:
                    amt = data["amt"]
                    unified_rows.append({
                        "_sort_date": pd.to_datetime(data["date"]), "_is_ledger": False, "_orig_idx": 999999, "取引No": tid,
                        "日付": data["date"], "摘要": data["desc"], "借方金額": abs(amt) if amt < 0 else 0, "貸方金額": amt if amt > 0 else 0,
                        "明細突合": "❌ 漏れ", "帳簿残高": None, "_actual_amt": amt
                    })
            
            df_master = pd.DataFrame(unified_rows).sort_values(["_sort_date", "_is_ledger", "_orig_idx"])
            df_master, last_bal = recalculate_balances(df_master, start_balance)
            
            st.session_state.result_df = df_master
            st.session_state.start_bal = start_balance
            st.session_state.current_bal = last_bal
            
            # 結果表示フラグをON
            st.session_state.is_calculated = True

        except Exception as e:
            st.error(f"エラー: {e}")

    # ==========================================
    # 💡 画面ジャンプを完全に防ぐ最新の表示エリア
    # ==========================================
    @fragment_decorator
    def interactive_results():
        df_base = st.session_state.result_df
        
        # 1. ユーザーの編集状態を読み取り、一時的な「仮想データ」を作成する
        virtual_df = df_base.copy()
        edits = st.session_state.get("main_editor", {}).get("edited_rows", {})
        master_indices = st.session_state.get("filtered_master_indices", [])
        
        if edits and master_indices:
            for pos_idx_str, col_edits in edits.items():
                pos_idx = int(pos_idx_str)
                if pos_idx < len(master_indices) and "明細突合" in col_edits:
                    master_idx = master_indices[pos_idx]
                    virtual_df.at[master_idx, "明細突合"] = col_edits["明細突合"]
                    
        # 仮想データを使って裏で残高を再計算
        virtual_df, virtual_curr_bal = recalculate_balances(virtual_df, st.session_state.start_bal)

        # 2. 上部の数字は仮想データを使ってリアルタイムに表示！
        st.success("✨ 照合完了。上部の数字は編集に合わせてリアルタイムに変動します。")
        
        missing_count = len(virtual_df[virtual_df["明細突合"] == "❌ 漏れ"])
        not_found_count = len(virtual_df[virtual_df["明細突合"] == "❓ 元データなし"])
        diff_count = len(virtual_df[virtual_df["明細突合"] == "⚠️ 差異あり"])
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("最終計算残高", f"{int(virtual_curr_bal):,} 円")
        m2.metric("❌ 漏れ (会計未登録)", f"{missing_count} 件")
        m3.metric("❓ 元データなし", f"{not_found_count} 件")
        m4.metric("⚠️ 差異あり", f"{diff_count} 件")
        
        st.divider()
        st.subheader("🔍 結果の絞り込み ＆ 取引No一括コピー")
        
        filter_options = ["✅ 済", "❌ 漏れ", "⚠️ 差異あり", "❓ 元データなし", "🏦 支払", "-"]
        col_f1, col_f2 = st.columns([2, 1])
        with col_f1:
            sel_status = st.multiselect("表示フィルター（❌や⚠️だけに絞り込めます）", filter_options, default=filter_options)
        
        # 3. 表に渡すデータは「元のまま（中身を変えない）」にする！
        df_filtered = df_base[df_base["明細突合"].isin(sel_status)].copy()
        st.session_state.filtered_master_indices = df_filtered.index.tolist()
        
        tx_ids = "\n".join([str(tid) for tid in df_filtered["取引No"] if str(tid) not in ["", "nan", "-"]])
        with col_f2:
            st.write(f"**表示中の件数: {len(df_filtered)} 件**")
            with st.expander("📋 表示中の取引Noを一括コピー"):
                if tx_ids:
                    st.caption("右上のアイコンをクリックでコピーできます↓")
                    st.code(tx_ids, language="text")
                else:
                    st.write("コピーできる取引Noがありません。")

        def format_bal(val):
            if pd.isna(val) or val is None or val == "-": return "-"
            if isinstance(val, (int, float)) and not math.isnan(val):
                return f"{int(val):,}"
            return val
            
        df_display = df_filtered.copy()
        df_display["帳簿残高"] = df_display["帳簿残高"].apply(format_bal)
        df_display["計算残高"] = df_display["計算残高"].apply(format_bal)

        st.write("💡 **表のステータスを変更すると、上の「最終計算残高」が瞬時に変わります。**")
        st.caption("※表が上にスクロールするのを防ぐため、表内の「計算残高」は下の確定ボタンを押すまで変わりません。")
        
        edit_cols = ["取引No", "日付", "摘要", "借方金額", "貸方金額", "明細突合", "帳簿残高", "計算残高", "残高照合"]
        
        st.data_editor(
            df_display[edit_cols].style.map(
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
            column_config={
                "明細突合": st.column_config.SelectboxColumn("明細突合", options=filter_options),
            },
            disabled=["取引No", "日付", "摘要", "借方金額", "貸方金額", "帳簿残高", "計算残高", "残高照合"],
            use_container_width=True,
            hide_index=True,
            key="main_editor" # データを更新しないので、編集しても一切ジャンプしません
        )
        
        # 4. 最後にまとめて表の計算を確定させるボタン
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button("💾 編集を確定して表の計算残高を更新 (※一番上に戻ります)", type="primary"):
                st.session_state.result_df = virtual_df
                st.session_state.current_bal = virtual_curr_bal
                st.rerun()
        with c_btn2:
            # ダウンロードボタンには、最新の計算結果（virtual_df）をそのまま渡します！
            csv_bytes = virtual_df[virtual_df["明細突合"].isin(sel_status)].to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 表示中の結果をダウンロード", io.BytesIO(csv_bytes), "突合結果_絞り込み.csv")

    # 実行判定
    if st.session_state.get("is_calculated", False):
        interactive_results()

elif file_ledger or file_card:
    st.warning("両方のファイルをアップロードしてください。")
