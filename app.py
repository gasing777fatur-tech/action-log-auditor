import streamlit as st
import re
import pandas as pd
import requests
from io import StringIO

st.set_page_config(page_title="Multi-Engine Action Log Auditor", layout="wide")
st.title("🛡️ ACTION LOG AUDITOR")

# ==============================================================================
# 1. HELPER CONVERT & LOAD CSV (STRICT & AUTO-OLD)
# ==============================================================================

def convert_gsheet_url(url, sheet_name=""):
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        return url
    spreadsheet_id = match.group(1)
    if sheet_name:
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(sheet_name)}"
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv"

def load_raw_csv_strict(url, sheet_name):
    """Membaca CSV dengan validasi ketat nama tab Google Sheet"""
    try:
        csv_url = convert_gsheet_url(url, sheet_name)
        response = requests.get(csv_url, timeout=10)
        
        if response.status_code != 200 or "html" in response.headers.get('Content-Type', '').lower():
            return None
            
        df_raw = pd.read_csv(StringIO(response.text), header=None)
        
        if df_raw.empty or (len(df_raw) == 1 and "html" in str(df_raw.iloc[0, 0]).lower()):
            return None
            
        return df_raw
    except Exception:
        return None

def parse_date(date_str):
    if pd.isna(date_str) or not str(date_str).strip():
        return None
    date_clean = str(date_str).strip().split('\n')[0].strip()
    formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d-%b-%Y %H:%M:%S', '%d-%b-%Y', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y']
    for fmt in formats:
        try:
            return pd.to_datetime(date_clean, format=fmt)
        except:
            pass
    try:
        return pd.to_datetime(date_clean, errors='coerce')
    except:
        return None

def to_bool(val):
    if pd.isna(val):
        return False
    s = str(val).strip().upper()
    return s in ["TRUE", "1", "YES", "Y"]

# ==============================================================================
# 2. PARSER ENGINE SPECIFICATIONS
# ==============================================================================

def process_jhn(df_raw):
    """ENGINE JHN Parser"""
    output = []
    
    for i in range(1, len(df_raw)):
        row = df_raw.iloc[i]

        created_at  = str(row[6]).split('\n')[0].strip() if len(row) > 6 and pd.notna(row[6]) else ""
        by_agent    = str(row[3]).strip().upper() if len(row) > 3 and pd.notna(row[3]) else ""
        username    = str(row[2]).strip().upper() if len(row) > 2 and pd.notna(row[2]) else ""
        action_val  = str(row[1]).strip().upper() if len(row) > 1 and pd.notna(row[1]) else ""
        logs_detail = str(row[10]).strip() if len(row) > 10 and pd.notna(row[10]) else ""
        ip_address  = str(row[4]).strip() if len(row) > 4 and pd.notna(row[4]) else ""
        status_val  = str(row[9]).strip().upper() if len(row) > 9 and pd.notna(row[9]) else ""

        if not created_at or created_at.upper() in ["CREATED AT", "CREATED_AT", "NAN", "NONE"]:
            continue
            
        if status_val != "SUCCESS":
            continue

        act_cat = action_val
        if action_val == 'MEMBER EDIT PROFILE':
            act_cat = "RESET PASSWORD"
        elif action_val == 'ADD MEMBER BANK ACCOUNT':
            act_cat = "ADD BANK ACCOUNT"
        elif action_val == 'EDIT MEMBER BANK ACCOUNT':
            act_cat = "EDIT BANK ACCOUNT"
        elif action_val == 'DELETE MEMBER BANK ACCOUNT':
            act_cat = "DELETE MEMBER BANK ACCOUNT"

        output.append({
            'CREATED AT': created_at,
            'BY AGENT': by_agent,
            'USERNAME': username,
            'SUB / TYPE': 'UPDATE',
            'ACTION': act_cat,
            'LOGS / DETAIL': logs_detail if logs_detail.lower() != 'nan' else '',
            'IP ADDRESS': ip_address if ip_address.lower() != 'nan' else ''
        })

    if not output:
        raise ValueError("Tidak ada data valid yang cocok untuk ENGINE JHN.")

    return pd.DataFrame(output)

def process_ug(df_raw):
    """ENGINE UG Parser - Anti Leak Header & Anti Typo Tab"""
    if df_raw is None or len(df_raw) <= 1:
        raise ValueError("Data raw ENGINE UG tidak mencukupi.")

    if len(df_raw.columns) < 8:
        raise ValueError("Format tab tidak cocok untuk ENGINE UG (jumlah kolom kurang).")

    output = []

    for i in range(1, len(df_raw)):
        row = df_raw.iloc[i]

        raw_h = str(row[7]) if len(row) > 7 and pd.notna(row[7]) else ""
        raw_f = str(row[5]) if len(row) > 5 and pd.notna(row[5]) else ""
        raw_g = str(row[6]) if len(row) > 6 and pd.notna(row[6]) else ""

        created_at = raw_h.split('\n')[0].strip() if raw_h else ""

        agent_match = re.search(r'\(([^)]+)\)', raw_f)
        by_agent = agent_match.group(1).strip().upper() if agent_match else raw_f.strip().upper()

        user_match = re.search(r'\(([^)]+)\)', raw_g)
        username = user_match.group(1).strip().upper() if user_match else raw_g.strip().upper()

        # 1. FILTER KETAT BARIS HEADER / TYPO TAB
        # Jika nilai kolom terdeteksi berisi teks header, langsung skip
        invalid_keywords = ["CREATED AT", "CREATED_AT", "BY AGENT", "LOGS / DETAIL", "LOGS/DETAIL", "IP ADDRESS", "USERNAME", "ACTION", "NAN", "NONE", ""]
        
        if created_at.upper() in invalid_keywords or username.upper() in invalid_keywords or by_agent.upper() in invalid_keywords:
            continue

        # 2. VALIDASI TANGGAL (Harus diawali angka tahun/tanggal, bukan teks bebas)
        if not re.match(r'^\d{2,4}', created_at):
            continue

        sub_type = str(row[2]).strip().upper() if len(row) > 2 and pd.notna(row[2]) else ""
        action_val = str(row[3]).strip().upper() if len(row) > 3 and pd.notna(row[3]) else ""
        logs_detail = str(row[4]).strip() if len(row) > 4 and pd.notna(row[4]) else ""

        ip_match = re.search(r'(?:[0-9]{1,3}\.){3}[0-9]{1,3}', raw_h)
        ip_address = ip_match.group(0) if ip_match else ""

        act_cat = action_val
        logs_lower = logs_detail.lower()

        if sub_type == 'MEMBER BANK' and action_val == 'CREATE':
            act_cat = "ADD BANK ACCOUNT"
        elif (sub_type == 'MEMBER DETAILS' or 'account name update' in logs_lower) and action_val != 'DELETE':
            act_cat = "EDIT BANK ACCOUNT"
        elif action_val == 'DELETE':
            act_cat = "DELETE BANK ACCOUNT"
        elif 'changed account password' in logs_lower:
            act_cat = "RESET PASSWORD"
        elif action_val == 'SUSPEND ON' or 'from no to suspended' in logs_lower:
            act_cat = "SUSPEND ACCOUNT"
        elif action_val == 'SUSPEND OFF' or 'from suspended to no' in logs_lower:
            act_cat = "UNSUSPEND ACCOUNT"
        elif action_val == 'STATUS OFF' or 'from on to off' in logs_lower:
            act_cat = "LOCK"
        elif action_val == 'STATUS ON' or 'from off to on' in logs_lower:
            act_cat = "UNLOCK"
        elif action_val == 'MANUAL ADJUSTMENT':
            act_cat = "ADJUSTMENT BALANCE"

        output.append({
            'CREATED AT': created_at,
            'BY AGENT': by_agent,
            'USERNAME': username,
            'SUB / TYPE': sub_type if sub_type != 'NAN' else '',
            'ACTION': act_cat,
            'LOGS / DETAIL': logs_detail if logs_detail.lower() != 'nan' else '',
            'IP ADDRESS': ip_address
        })

    # Jika setelah difilter hasilnya kosong (karena typo tab), lemparkan error peringatan
    if not output:
        raise ValueError("Tidak ada data valid yang cocok untuk ENGINE UG.")
    
    df_res = pd.DataFrame(output)
    return df_res

def process_zoom(df_raw, df_password=None):
    """ENGINE ZOOM Parser - Mengikuti Indeks Kolom Kaku Tab Utama vs Password"""
    output = []

    # 1. Parse Tab Utama ZOOM
    if df_raw is not None and len(df_raw) > 1:
        # Pengecekan aman dari float / NaN
        header_row = [str(col).upper() for col in df_raw.iloc[0].fillna('').tolist()]
        has_created_at = any("CREATED" in col for col in header_row)
        
        if has_created_at:
            for i in range(1, len(df_raw)):
                row = df_raw.iloc[i]

                created_at = str(row[33]).split('\n')[0].strip() if len(row) > 33 and pd.notna(row[33]) else "" 
                by_agent   = str(row[32]).strip().upper() if len(row) > 32 and pd.notna(row[32]) else ""     
                username   = str(row[1]).strip().upper() if len(row) > 1 and pd.notna(row[1]) else ""        
                full_name  = str(row[2]).strip() if len(row) > 2 and pd.notna(row[2]) else ""                
                bank_name  = str(row[15]).strip() if len(row) > 15 and pd.notna(row[15]) else ""            
                bank_acc   = str(row[16]).strip() if len(row) > 16 and pd.notna(row[16]) else ""            
                status_val = str(row[17]).strip().upper() if len(row) > 17 and pd.notna(row[17]) else ""     
                reason_val = str(row[18]).strip() if len(row) > 18 and pd.notna(row[18]) else ""              
                remark_val = str(row[26]).strip() if len(row) > 26 and pd.notna(row[26]) else ""              
                action_raw = str(row[34]).strip().lower() if len(row) > 34 and pd.notna(row[34]) else ""     

                if not created_at or created_at.upper() in ["CREATED AT", "CREATED_AT", "NAN", "NONE"]:
                    continue

                act_cat = "OTHER ACTION"
                status_lower = status_val.lower()

                if action_raw == "update player full name":
                    act_cat = "UPDATE FULL NAME"
                elif action_raw == "insert player bank account":
                    act_cat = "ADD BANK ACCOUNT"
                elif action_raw == "delete player bank account":
                    act_cat = "DELETE BANK ACCOUNT"
                elif action_raw == "update profile":
                    if re.search(r'new\s*:\s*suspend', status_lower):
                        act_cat = "SUSPEND ACCOUNT"
                    elif re.search(r'new\s*:\s*inactive', status_lower):
                        act_cat = "INACTIVE ACCOUNT"
                    elif remark_val != "" and not re.search(r'suspend|inactive', status_lower):
                        act_cat = "UPDATE REMARK"
                    else:
                        act_cat = "UPDATE PROFILE"

                output.append({
                    'CREATED AT': created_at,
                    'BY AGENT': by_agent,
                    'USERNAME': username,
                    'FULL NAME': full_name,
                    'BANK ACCOUNT NAME': bank_name,
                    'BANK ACCOUNT': bank_acc,
                    'STATUS': status_val,
                    'REASON': reason_val,
                    'REMARK': remark_val,
                    'ACTION TYPE': act_cat
                })

    # 2. Parse Tab Password ZOOM
    if df_password is not None and len(df_password) > 1:
        pwd_header = [str(col).upper() for col in df_password.iloc[0].fillna('').tolist()]
        
        # Pengecekan aman nilai string pada header password
        is_valid_pwd_tab = len(pwd_header) > 3 and ("AGENT" in pwd_header[2] or "CREATED" in pwd_header[3])
        
        if is_valid_pwd_tab:
            for i in range(1, len(df_password)):
                row = df_password.iloc[i]

                created_at = str(row[3]).split('\n')[0].strip() if len(row) > 3 and pd.notna(row[3]) else ""  
                by_agent   = str(row[2]).strip().upper() if len(row) > 2 and pd.notna(row[2]) else ""      
                username   = str(row[1]).strip().upper() if len(row) > 1 and pd.notna(row[1]) else ""      

                if not created_at or created_at.upper() in ["CREATED AT", "CREATED_AT", "NAN", "NONE"]:
                    continue

                output.append({
                    'CREATED AT': created_at,
                    'BY AGENT': by_agent,
                    'USERNAME': username,
                    'FULL NAME': '',
                    'BANK ACCOUNT NAME': '',
                    'BANK ACCOUNT': '',
                    'STATUS': '',
                    'REASON': '',
                    'REMARK': '',
                    'ACTION TYPE': 'RESET PASSWORD'
                })

    if not output:
        raise ValueError("Tidak ada data valid yang cocok untuk ENGINE ZOOM.")

    df_res = pd.DataFrame(output)
    df_res = df_res.sort_values(by=['CREATED AT'], ascending=[True]).reset_index(drop=True)
    return df_res

def process_idn(df_raw):
    """ENGINE IDN Parser"""
    if df_raw is None or len(df_raw) <= 1:
        raise ValueError("Data raw ENGINE IDN tidak mencukupi.")

    output = []

    for i in range(1, len(df_raw)):
        row = df_raw.iloc[i]

        # CUKUP PERBAIKI INDEKS BY AGENT KE row[1] (KOLOM B):
        by_agent = str(row[1]).strip().upper() if len(row) > 1 and pd.notna(row[1]) else ""
        raw_type  = str(row[2]).strip() if len(row) > 2 and pd.notna(row[2]) else ""
        raw_logs  = str(row[3]).strip() if len(row) > 3 and pd.notna(row[3]) else ""
        raw_ip    = str(row[4]).strip() if len(row) > 4 and pd.notna(row[4]) else ""
        raw_date  = str(row[5]).split('\n')[0].strip() if len(row) > 5 and pd.notna(row[5]) else ""

        if not raw_date or raw_date.upper() in ["CREATED AT", "CREATED_AT", "NAN", "NONE"]:
            continue

        clean_type = raw_type.upper().replace("_", " ")
        clean_flat_log = raw_logs.replace("\n", " ")
        clean_flat_log_lower = clean_flat_log.lower()

        match_prof = re.search(r'updated player profile (\S+)', clean_flat_log, re.IGNORECASE)
        match_id   = re.search(r'player\s*(?:id)?\s*(?::)?\s*(\S+)', clean_flat_log, re.IGNORECASE)
        
        if match_prof:
            username = match_prof.group(1).upper()
        elif match_id:
            username = match_id.group(1).upper()
        else:
            username = "-"

        is_profile = "updated player profile" in clean_flat_log_lower
        is_pass    = "update password" in clean_flat_log_lower
        is_block   = "blocked player" in clean_flat_log_lower
        is_unblock = bool(re.search(r'un\s*blocked', clean_flat_log_lower))
        is_json    = "original data:" in clean_flat_log_lower

        orig_fn  = re.search(r'Original Data:.*?"user_fullname":"([^"]*)', clean_flat_log)
        upd_fn   = re.search(r'Updated Data:.*?"user_fullname":"([^"]*)', clean_flat_log)
        orig_bn  = re.search(r'Original Data:.*?"bank_name":"([^"]*)', clean_flat_log)
        upd_bn   = re.search(r'Updated Data:.*?"bank_name":"([^"]*)', clean_flat_log)
        orig_ba  = re.search(r'Original Data:.*?"bank_account":"([^"]*)', clean_flat_log)
        upd_ba   = re.search(r'Updated Data:.*?"bank_account":"([^"]*)', clean_flat_log)
        orig_num = re.search(r'Original Data:.*?"bank_number":"([^"]*)', clean_flat_log)
        upd_num  = re.search(r'Updated Data:.*?"bank_number":"([^"]*)', clean_flat_log)
        orig_ds  = re.search(r'Original Data:.*?"user_desc":"([^"]*)', clean_flat_log)
        upd_ds   = re.search(r'Updated Data:.*?"user_desc":"([^"]*)', clean_flat_log)

        ofn = orig_fn.group(1) if orig_fn else ""
        ufn = upd_fn.group(1) if upd_fn else ""
        obn = orig_bn.group(1) if orig_bn else ""
        ubn = upd_bn.group(1) if upd_bn else ""
        oba = orig_ba.group(1) if orig_ba else ""
        uba = upd_ba.group(1) if upd_ba else ""
        onum = orig_num.group(1) if orig_num else ""
        unum = upd_num.group(1) if upd_num else ""
        ods = orig_ds.group(1) if orig_ds else ""
        uds = upd_ds.group(1) if upd_ds else ""

        chg_fn = "FULLNAME" if ofn != ufn else ""
        chg_bk = "BANK, ACCOUNT NUMBER" if (obn != ubn or onum != unum) else ""
        chg_ba = "A/N" if oba != uba else ""
        chg_ds = "DESCRIPTION" if ods != uds else ""

        hdr_parts = [p for p in [chg_fn, chg_bk, chg_ba, chg_ds] if p]
        hdr_list  = ", ".join(hdr_parts)

        has_profile_change = (ofn != ufn) or (obn != ubn) or (oba != uba) or (onum != unum)
        has_desc_change    = (ods != uds)

        calc_action = None
        if is_pass:
            calc_action = "RESET PASSWORD"
        elif is_unblock:
            calc_action = "UNSUSPEND ACCOUNT"
        elif is_block:
            calc_action = "SUSPEND ACCOUNT"
        elif is_profile:
            if has_profile_change:
                calc_action = "EDIT BANK ACCOUNT"
            elif has_desc_change:
                calc_action = "UPDATE REMARK"

        if not calc_action:
            continue

        if is_pass:
            detail_log = re.sub(r'(update password)', r'\n\1', clean_flat_log, flags=re.IGNORECASE)
        elif is_unblock:
            detail_log = re.sub(r'(un\s*blocked player)', r'\nunblocked player', clean_flat_log, flags=re.IGNORECASE)
        elif is_block:
            detail_log = re.sub(r'(blocked player)', r'\n\1', clean_flat_log, flags=re.IGNORECASE)
        elif is_profile:
            if is_json:
                changes = []
                if ofn != ufn:
                    changes.append(f"From Fullname: {ofn} > To Fullname: {ufn}")
                if obn != ubn or onum != unum:
                    changes.append(f"From Bank: {obn.upper()} ({onum}) > To Bank: {ubn.upper()} ({unum})")
                if oba != uba:
                    changes.append(f"From Account Name: {oba} > To Account Name: {uba}")
                if ods != uds:
                    ods_str = "[KOSONG]" if ods == "" else ods
                    uds_str = "[KOSONG]" if uds == "" else uds
                    changes.append(f"From Desc: {ods_str} > To Desc: {uds_str}")

                body_changes = "\n".join(changes) if changes else "No detailed changes"
                detail_log = f"Update Member Details ({hdr_list})\n{body_changes}"
            else:
                detail_log = re.sub(r'(updated player profile)', r'\n\1', clean_flat_log, flags=re.IGNORECASE)
        else:
            detail_log = clean_flat_log

        output.append({
            'CREATED AT': raw_date,
            'BY AGENT': by_agent,
            'USERNAME': username,
            'SUB / TYPE': clean_type,
            'ACTION': calc_action,
            'LOGS / DETAIL': detail_log.strip(),
            'IP ADDRESS': raw_ip
        })

    if not output:
        raise ValueError("Tidak ada data valid yang cocok untuk ENGINE IDN.")

    df_res = pd.DataFrame(output)
    df_res = df_res.sort_values(by=['ACTION', 'CREATED AT'], ascending=[True, True]).reset_index(drop=True)
    return df_res

def process_tmt_j3(df_raw):
    """ENGINE TMT & J3 Parser"""
    header_found = False
    start_row = 2
    
    for check_idx in range(min(5, len(df_raw))):
        row_str = " ".join([str(val).upper() for val in df_raw.iloc[check_idx].values])
        if ("USERNAME" in row_str or "PLAYER" in row_str) and ("BANK" in row_str or "PASSWORD" in row_str or "PASS" in row_str):
            header_found = True
            start_row = check_idx + 1
            break
            
    if not header_found:
        raise ValueError("Format header tidak cocok dengan ENGINE TMT & J3. Kemungkinan nama tab salah!")

    data = []
    for i in range(start_row, len(df_raw)):
        row = df_raw.iloc[i]
        
        raw_player = str(row[0]).strip() if pd.notna(row[0]) else ""
        if not raw_player or raw_player.upper() in ["USERNAME", "PLAYER", "NAN", "NONE"]:
            continue
            
        clean_player = re.split(r'[\r\n]', raw_player)[0].strip().upper()
        raw_pass     = str(row[1]).strip() if pd.notna(row[1]) else ""
        raw_bank     = str(row[2]).strip() if pd.notna(row[2]) else ""
        raw_note     = str(row[4]).strip() if (len(row) > 4 and pd.notna(row[4])) else ""
        raw_act      = to_bool(row[5]) if len(row) > 5 else True
        raw_sus      = to_bool(row[6]) if len(row) > 6 else False
        raw_date     = str(row[7]).split('\n')[0].strip() if (len(row) > 7 and pd.notna(row[7])) else ""
        raw_by       = str(row[8]).strip().upper() if (len(row) > 8 and pd.notna(row[8])) else ""

        if raw_date.upper() in ["TRUE", "FALSE", ""]:
            continue

        data.append({
            'raw_player': raw_player,
            'clean_player': clean_player,
            'raw_pass': raw_pass,
            'raw_bank': raw_bank,
            'raw_note': raw_note,
            'raw_act': raw_act,
            'raw_sus': raw_sus,
            'raw_date': raw_date,
            'clean_by': raw_by
        })

    if not data:
        raise ValueError("Tidak ada data valid yang cocok untuk ENGINE TMT & J3.")

    df_temp = pd.DataFrame(data)

    df_temp['prev_sus'] = df_temp.groupby('clean_player')['raw_sus'].shift(1)
    df_temp['prev_bank'] = df_temp.groupby('clean_player')['raw_bank'].shift(1).fillna("")

    output = []
    for _, row in df_temp.iterrows():
        ss = row['raw_sus']
        prev_sus = row['prev_sus']
        ac = row['raw_act']
        ps = row['raw_pass']
        bk = row['raw_bank']
        prev_bank = str(row['prev_bank']).strip()
        nt = row['raw_note']
        by = row['clean_by']
        pl = row['clean_player']

        if prev_sus == True and ss == False:
            act = "UNSUSPEND ACCOUNT"
        elif ss == True:
            act = "SUSPEND ACCOUNT"
        elif ac == False:
            act = "INACTIVE ACCOUNT"
        elif ps.lower() == "yes":
            act = "RESET PASSWORD"
        elif prev_bank != "" and bk != "" and bk != prev_bank:
            act = "EDIT BANK ACCOUNT"
        elif nt != "":
            act = "UPDATE REMARK"
        else:
            act = "OTHER ACTION"

        if act == "UNSUSPEND ACCOUNT":
            detail = f"Agent {by}\nupdate suspend status to FALSE\nfor Player: {pl}"
        elif act == "SUSPEND ACCOUNT":
            detail = f"Agent {by}\nupdate suspend status to TRUE\nfor Player: {pl}"
        elif act == "INACTIVE ACCOUNT":
            detail = f"Agent {by}\nupdate active status to FALSE\nfor Player: {pl}"
        elif act == "RESET PASSWORD":
            detail = f"Agent {by}\nupdate password status to YES\nfor Player: {pl}"
        elif act == "EDIT BANK ACCOUNT":
            bk_clean = bk.replace('\n', ' - ')
            detail = f"Agent {by}\nupdate bank details to [{bk_clean}]\nfor Player: {pl}"
        elif act == "UPDATE REMARK":
            nt_clean = nt.replace('\n', ' ')
            detail = f"Agent {by}\nupdate note to [{nt_clean}]\nfor Player: {pl}"
        else:
            detail = f"Agent {by}\nprocessed activity\non Player: {pl}"

        output.append({
            'CREATED AT': row['raw_date'],
            'BY AGENT': by,
            'USERNAME': pl,
            'BANK ACCOUNT': bk,
            'ACTION': act,
            'LOGS / DETAIL': detail,
            'ACTIVE': "TRUE" if ac else "FALSE",
            'SUSPEND': "TRUE" if ss else "FALSE"
        })

    df_res = pd.DataFrame(output)
    df_res = df_res.sort_values(by=['ACTION', 'CREATED AT'], ascending=[True, True]).reset_index(drop=True)
    return df_res

# ==============================================================================
# 3. SIDEBAR INTERFACE
# ==============================================================================

st.sidebar.header("🎯 System Controls")

gsheet_url = st.sidebar.text_input("1. Google Sheet Link :")
engine_choice = st.sidebar.selectbox(
    "2. Select Action Log Engine:",
    ["ENGINE JHN", "ENGINE UG", "ENGINE ZOOM", "ENGINE TMT & J3", "ENGINE IDN"]
)
sheet_name = st.sidebar.text_input("3. Nama Tab / Web (Ketik Manual):", placeholder="Harus Sesuai Nama Tab Sheet").strip()

st.sidebar.subheader("🔍 Search Username")
search_username = st.sidebar.text_input("Username:", placeholder="Cari Username...").strip()

st.sidebar.subheader("📅 Date Range Filter (Opsional)")
enable_date_filter = st.sidebar.checkbox("Aktifkan Filter Tanggal", value=False)
start_date, end_date = None, None
if enable_date_filter:
    start_date = st.sidebar.date_input("Start Date")
    end_date = st.sidebar.date_input("End Date")

# ==============================================================================
# 4. MAIN EXECUTION FLOW (INDEPENDENT FILTER LOGIC)
# ==============================================================================

if gsheet_url and sheet_name:
    raw_df = load_raw_csv_strict(gsheet_url, sheet_name)

    # STRICT VALIDATION UNTUK TAB UTAMA (Berlaku Seragam Untuk Semua Engine)
    if raw_df is None:
        st.error(f"❌ Tab **'{sheet_name}'** TIDAK DITEMUKAN di Google Sheet ini! Pastikan ejaan nama tab sudah benar.")
        st.stop()

    old_sheet_name = f"{sheet_name}_OLD" if not sheet_name.endswith("_OLD") else ""
    raw_df_old = load_raw_csv_strict(gsheet_url, old_sheet_name) if old_sheet_name else None

    try:
        if engine_choice == "ENGINE JHN":
            parser_fn = process_jhn
            df_processed = parser_fn(raw_df)

        elif engine_choice == "ENGINE UG":
            parser_fn = process_ug
            df_processed = parser_fn(raw_df)

        elif engine_choice == "ENGINE ZOOM":
            pwd_sheet_name = f"{sheet_name}_password"
            raw_df_pwd = load_raw_csv_strict(gsheet_url, pwd_sheet_name)

            df_processed = process_zoom(raw_df, raw_df_pwd)

            if old_sheet_name and raw_df_old is not None:
                raw_df_old_pwd = load_raw_csv_strict(gsheet_url, f"{old_sheet_name}_password")
                try:
                    df_old_processed = process_zoom(raw_df_old, raw_df_old_pwd)
                    df_processed = pd.concat([df_processed, df_old_processed], ignore_index=True)
                    st.toast(f"Data gabungan dari {sheet_name} (+ OLD: {old_sheet_name}) berhasil dimuat!", icon="ℹ️")
                except Exception:
                    pass

        elif engine_choice == "ENGINE TMT & J3":
            parser_fn = process_tmt_j3
            df_processed = parser_fn(raw_df)

        elif engine_choice == "ENGINE IDN":
            parser_fn = process_idn
            df_processed = parser_fn(raw_df)

        # Process & Combine _OLD Sheet untuk Engine non-ZOOM
        if engine_choice != "ENGINE ZOOM" and raw_df_old is not None:
            try:
                df_old_processed = parser_fn(raw_df_old)
                df_processed = pd.concat([df_processed, df_old_processed], ignore_index=True)
                st.toast(f"Data gabungan dari {sheet_name} (+ OLD: {old_sheet_name}) berhasil dimuat!", icon="ℹ️")
            except Exception:
                pass

        # ----------------------------------------------------------------------
        # INDEPENDENT SIDEBAR FILTER LOGIC
        # ----------------------------------------------------------------------
        action_col = 'ACTION' if 'ACTION' in df_processed.columns else 'ACTION TYPE'

        # 1. Ambil Opsi Dropdown Murni dari Seluruh Data Master (df_processed)
        all_agents = ["ALL"] + sorted([str(x) for x in df_processed['BY AGENT'].dropna().unique() if str(x).strip() != ""])

        if engine_choice == "ENGINE IDN":
            all_actions = ["ALL ACTION", "EDIT BANK ACCOUNT", "UPDATE REMARK", "RESET PASSWORD", "SUSPEND ACCOUNT", "UNSUSPEND ACCOUNT"]
        else:
            all_actions = ["ALL ACTION"] + sorted([str(x) for x in df_processed[action_col].dropna().unique() if str(x).strip() != ""])

        # 2. Render Widget Dropdown Filter
        selected_agent = st.sidebar.selectbox("Filter Agent / Handler:", all_agents)
        selected_action = st.sidebar.selectbox("Filter Kategori Action:", all_actions)

        # 3. Terapkan Seluruh Filter Secara Paralel ke Output Dataframe
        df_filtered = df_processed.copy()

        # Filter Tanggal
        if enable_date_filter and start_date and end_date:
            df_filtered['parsed_date'] = df_filtered['CREATED AT'].apply(parse_date)
            mask = (df_filtered['parsed_date'].dt.date >= start_date) & (df_filtered['parsed_date'].dt.date <= end_date)
            df_filtered = df_filtered[mask]

        # Filter Agent
        if selected_agent != "ALL":
            df_filtered = df_filtered[df_filtered['BY AGENT'] == selected_agent]

        # Filter Action Category
        if selected_action != "ALL ACTION":
            df_filtered = df_filtered[df_filtered[action_col] == selected_action]

        # Filter Username Search (Independen di Luar Dropdown)
        if search_username and 'USERNAME' in df_filtered.columns:
            df_filtered = df_filtered[
                df_filtered['USERNAME'].astype(str).str.contains(search_username, case=False, na=False)
            ]

        # ----------------------------------------------------------------------
        # MAIN UI DISPLAY
        # ----------------------------------------------------------------------
        combined_title = sheet_name
        st.subheader(f"📊 Handler Action Log Count ({combined_title})")
        if selected_agent != "ALL":
            st.info(f"Breakdown Action Log untuk Handler: **{selected_agent}**")
            agent_counts = df_filtered[action_col].value_counts().reset_index()
            agent_counts.columns = ['Jenis Action', 'Jumlah Action']
            st.dataframe(agent_counts, hide_index=True, use_container_width=True)
        else:
            st.write("Pilih Agent spesifik di sidebar untuk melihat breakdown action per jenis.")

        st.divider()
        st.subheader(f"📋 Audit Log Activity ({engine_choice} - {combined_title}) - Total: {len(df_filtered)} Rows")

        display_cols = [c for c in df_filtered.columns if c != 'parsed_date']
        st.dataframe(df_filtered[display_cols], use_container_width=True, hide_index=True)

    except ValueError as ve:
        st.warning(f"⚠️ {ve}")
    except Exception as e:
        st.error(f"Terjadi kesalahan saat memproses data: {e}")
