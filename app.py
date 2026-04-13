import streamlit as st
import pandas as pd
import io
from datetime import datetime, date

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

# --- 🚀 2. メインUI (CSV専用 爆速版) ---
st.title("会計ソフト × クレカ明細 ⚡ 爆速CSV突合ツール")
st.info("AIを使わず、プログラムで直接データを照合するため一瞬で終わります。")

# CSV読み込み用のヘルパー関数
def load_csv(file):
    if file is not None:
        for enc in ["utf-8-sig", "shift_jis", "cp932"]:
            try:
                file.seek(0)
                return pd.read_csv(file, encoding=enc)
            except:
                continue
    return None

st.subheader("📁 1. ファイルをアップロード")
col1, col2 = st.columns(2)
with col1:
    csv_ledger_file = st.file_uploader("会計ソフト (MF・freee等)", type=["csv"], key="ledger")
with col2:
    csv_card_file = st.file_uploader("クレカ明細 (各カード会社のCSV)", type=["csv"], key="card")

df_ledger = load_csv(csv_ledger_file)
df_card_raw = load_csv(csv_card_file)

if df_ledger is not None:
    st.success("✅ 会計ソフトのデータを読み込みました")

if df_card_raw is not None:
    st.success("✅ クレカ明細のデータを読み込みました")
    
    st.markdown("---")
    st.subheader("⚙️ 2. クレカ明細の列を設定")
    st.write("カード会社によって列の名前が違うため、該当する列を選んでください。")
    
    # プレビュー表示
    with st.expander("👀 クレカ明細のデータプレビュー (最初の5件)"):
        st.dataframe(df_card_raw.head())
    
    columns = df_card_raw.columns.tolist()
    
    # ユーザーに列を選ばせる
    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1:
        date_col = st.selectbox("📅 日付の列", columns, index=0)
    with col_c2:
        desc_col = st.selectbox("📝 摘要(店名)の列", columns, index=min(1, len(columns)-1))
    with col_c3:
        amt_col = st.selectbox("💰 金額の列", columns, index=min(2, len(columns)-1))

    st.markdown("---")
    st.subheader("🗓️ 3. 期間と残高の設定")
    
    # 日付のデフォルト値を今年に
    this_year = datetime.now().year
    
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        start_date = st.date_input("開始日", value=date(this_year, 1, 1))
    with col_s2:
        end_date = st.date_input("終了日", value=date(this_year, 12, 31))
    with col_s3:
        start_balance = st.number_input("期首残高（開始日の前日時点）", value=0)

    # 実行ボタン
    if df_ledger is not None and st.button("🚀 突合スタート！ (1秒で終わります)"):
        try:
            # 必要な列だけを抽出してリネーム
            df_card = df_card_raw[[date_col, desc_col, amt_col]].copy()
            df_card.columns = ["date", "description", "amount"]
            
            # 日付の変換とフィルタリング
            df_card["date"] = pd.to_datetime(df_card["date"], errors="coerce")
            df_card = df_card.dropna(subset=["date"])
            mask = (df_card["date"].dt.date >= start_date) & (df_card["date"].dt.date <= end_date)
            df_card = df_card.loc[mask].sort_values("date").reset_index(drop=True)
            
            if df_card.empty:
                st.warning("指定された期間のデータが見つかりませんでした。")
            else:
                # 金額のクレンジング (カンマ、￥、マイナス記号のブレを修正)
                def clean_amount(val):
                    try:
                        v_str = str(val).replace(',', '').replace('¥', '').replace(' ', '').replace('▲', '-')
                        # 空白やNaNの場合は0にする
                        if pd.isna(val) or v_str == '' or v_str == 'nan':
                            return 0
                        return int(float(v_str))
                    except:
                        return 0
                
                df_card["amount_clean"] = df_card["amount"].apply(clean_amount)
                
                # ゼロ円の行（決済じゃない行など）は除外してもOK
                df_card = df_card[df_card["amount_clean"] != 0].copy()
                
                # 残高計算
                df_card["計算残高"] = start_balance - df_card["amount_clean"].cumsum()
                
                # 会計ソフト側の全データを文字列セットにして検索を超高速化
                ledger_values = set(df_ledger.astype(str).values.flatten())
                
                # 突合ロジック
                def check_matching(amt):
                    return "✅ 済" if str(amt) in ledger_values else "❌ 漏れ"
                
                df_card["状況"] = df_card["amount_clean"].apply(check_matching)
                
                # 表示用に日付を整形
                df_card["date"] = df_card["date"].dt.strftime("%m/%d")
                
                # 必要な列だけを綺麗に表示
                df_result = df_card[["状況", "date", "description", "amount_clean", "計算残高"]].rename(
                    columns={"date": "日付", "description": "摘要", "amount_clean": "金額"}
                )
                
                st.success("✨ 突合が完了しました！")
                st.divider()
                
                m1, m2, m3 = st.columns(3)
                m1.metric("最終計算残高", f"{int(df_result['計算残高'].iloc[-1]):,} 円")
                m2.metric("抽出件数", f"{len(df_result)} 件")
                m3.metric("未連携(漏れ)の数", f"{len(df_result[df_result['状況'] == '❌ 漏れ'])} 件")
                
                st.dataframe(
                    df_result.style.map(
                        lambda x: "background-color: #ffcccc; color: #900;" if x == "❌ 漏れ" else "",
                        subset=["状況"]
                    ),
                    use_container_width=True
                )
                
                # CSVダウンロード機能
                csv_bytes = df_result.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    label="📥 結果をCSVでダウンロード",
                    data=io.BytesIO(csv_bytes),
                    file_name=f"突合結果_{start_date}_{end_date}.csv",
                    mime="text/csv",
                )
                
        except Exception as e:
            st.error(f"エラーが発生しました: {e}\n列の選択が間違っていないか確認してください。")
