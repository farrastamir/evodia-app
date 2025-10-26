import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from google.oauth2.service_account import Credentials
import json
import io
from datetime import datetime

# =======================================================================
# KONFIGURASI APLIKASI
# =======================================================================

# Mengatur konfigurasi halaman Streamlit
st.set_page_config(
    page_title="Evodia Management App",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded" # Sidebar default terbuka di desktop
)

# Judul utama aplikasi
st.title("🌿 Aplikasi Manajemen Bisnis Evodia v3.1")

# Ambil konfigurasi dari st.secrets
try:
    GCP_CREDS = st.secrets["gcp_service_account"]
    SHEET_URL = st.secrets["google_sheet"]["url"]
except (KeyError, FileNotFoundError):
    st.error("⚠️ Gagal memuat file 'secrets.toml'. Pastikan Anda telah mengikuti `setup_instructions.md` dan meng-klik 'Save' di Streamlit Cloud Secrets.")
    st.stop()

# Definisikan nama-nama tab dan kolomnya sesuai PRD (v3.1)
# Menambahkan 'sub_category' ke 'purchase_orders'
TAB_CONFIG = {
    "sales_orders": [
        "receipt_id", "date", "client_name", "product_name", 
        "product_quantity", "total_purchase", "payment_method", "status"
    ],
    "purchase_orders": [
        "purchase_id", "date", "category", "sub_category", "supplier_name", 
        "material_name", "quantity", "unit_of_measure", "price", 
        "payment_system", "status"
    ],
    "inventory_stock": [
        "material_id", "material_name", "supplier_name", 
        "category", "current_stock", "unit_of_measure"
    ],
    "products_bom": [
        "product_name", "components"
    ]
}

# =======================================================================
# GAYA / STYLING (CSS - Req Poin 1 + Update v3.2)
# =======================================================================
st.markdown(f"""
<style>
    /* Latar belakang utama */
    .stApp {{
        background-color: #F0F8FF; /* AliceBlue */
    }}

    /* Sidebar */
    [data-testid="stSidebar"] > div:first-child {{
        background-color: #6A5ACD; /* SlateBlue */
        color: white;
    }}
    [data-testid="stSidebar"] .stRadio [data-testid="stWidgetLabel"] > div {{
        color: white; /* Warna teks radio button di sidebar */
        font-size: 1.05rem; /* Perbesar sedikit */
        font-weight: 500;
    }}
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {{
        color: white; /* Warna label opsi radio */
        padding: 8px 10px; /* Tambah padding agar terlihat seperti tombol */
        border-radius: 8px;
        transition: background-color 0.3s ease;
    }}
    /* --- CSS BARU v3.2: Sembunyikan titik radio --- */
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label div[data-baseweb="radio"] {{
        display: none;
    }}
    /* --- CSS BARU v3.2: Efek hover pada 'tombol' menu --- */
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover {{
        background-color: #7B68EE; /* MediumSlateBlue (sedikit lebih terang) */
    }}

    /* Tombol Aksi - UPDATE v3.2: Tambah Animasi */
    div[data-testid="stButton"] > button,
    div[data-testid="stFormSubmitButton"] > button {{
        background-color: #FF69B4; /* HotPink */
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        transition: all 0.2s ease-in-out; /* <-- ANIMASI */
    }}
    div[data-testid="stButton"] > button:hover,
    div[data-testid="stFormSubmitButton"] > button:hover {{
        background-color: #FF1493; /* DeepPink (hover) */
        transform: scale(1.03); /* <-- ANIMASI */
        box-shadow: 0 4px 15px rgba(255, 105, 180, 0.4); /* <-- ANIMASI */
    }}
    div[data-testid="stButton"] > button:active,
    div[data-testid="stFormSubmitButton"] > button:active {{
        transform: scale(0.98); /* <-- ANIMASI (Click effect) */
        background-color: #C71585; /* MediumVioletRed */
    }}
    
    /* Aksen Judul */
    h1, h2 {{
        color: #6A5ACD; /* SlateBlue */
    }}
</style>
""", unsafe_allow_html=True)


# =======================================================================
# FUNGSI KONEKSI & INISIALISASI DATABASE (Req Poin 2)
# =======================================================================

# Menggunakan cache_resource untuk koneksi agar tidak perlu login ulang setiap refresh
@st.cache_resource
def connect_to_gsheet():
    """Menghubungkan ke Google Sheets menggunakan Service Account."""
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        if isinstance(GCP_CREDS, str):
            creds_dict = json.loads(GCP_CREDS)
        else:
            creds_dict = dict(GCP_CREDS)
            
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(SHEET_URL)
        return spreadsheet
    except Exception as e:
        st.error(f"Gagal terhubung ke Google Sheets: {e}. Cek kembali `secrets.toml` Anda.")
        st.stop()

@st.cache_data(ttl=300) # Cache data selama 5 menit
def load_data(worksheet_name):
    """Memuat data dari tab tertentu ke dalam Pandas DataFrame."""
    try:
        worksheet = sh.worksheet(worksheet_name)
        df = get_as_dataframe(worksheet, header=0, parse_dates=True, usecols=lambda x: x not in ['', None])
        df = df.dropna(axis=1, how='all')
        
        # Pastikan semua kolom yang diharapkan ada, jika tidak tambahkan sebagai kolom kosong
        expected_cols = TAB_CONFIG.get(worksheet_name, [])
        for col in expected_cols:
            if col not in df.columns:
                df[col] = pd.NA
        
        # Konversi tipe data penting
        if worksheet_name == 'inventory_stock' and 'current_stock' in df.columns:
            df['current_stock'] = pd.to_numeric(df['current_stock'], errors='coerce').fillna(0)
        if worksheet_name == 'sales_orders' and 'product_quantity' in df.columns:
            df['product_quantity'] = pd.to_numeric(df['product_quantity'], errors='coerce').fillna(0)
        if worksheet_name == 'purchase_orders' and 'quantity' in df.columns:
            df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
            
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Tab '{worksheet_name}' tidak ditemukan. Menjalankan inisialisasi...")
        initialize_database(sh) # Coba inisialisasi jika tab tidak ada
        return pd.DataFrame(columns=TAB_CONFIG[worksheet_name])
    except Exception as e:
        st.error(f"Gagal memuat data dari '{worksheet_name}': {e}")
        return pd.DataFrame(columns=TAB_CONFIG.get(worksheet_name, []))

def initialize_database(spreadsheet):
    """Memeriksa apakah semua tab yang diperlukan ada, jika tidak, buat tab tersebut."""
    existing_tabs = [ws.title for ws in spreadsheet.worksheets()]
    setup_performed = False
    
    with st.spinner("Memeriksa integritas database (Google Sheets)..."):
        for tab_name, headers in TAB_CONFIG.items():
            if tab_name not in existing_tabs:
                st.warning(f"Tab '{tab_name}' tidak ditemukan. Membuat tab baru...")
                try:
                    new_ws = spreadsheet.add_worksheet(title=tab_name, rows=100, cols=len(headers))
                    new_ws.append_row(headers)
                    st.success(f"Tab '{tab_name}' berhasil dibuat dengan header.")
                    setup_performed = True
                except Exception as e:
                    st.error(f"Gagal membuat tab '{tab_name}': {e}")
    
    if setup_performed:
        st.success("Inisialisasi database selesai. Harap refresh halaman.")
        st.cache_data.clear() # Hapus cache setelah setup
        st.stop()

def update_worksheet(worksheet_name, df):
    """Menulis ulang seluruh worksheet dengan data dari DataFrame."""
    try:
        worksheet = sh.worksheet(worksheet_name)
        # Konversi kolom tanggal ke string sebelum menyimpan untuk menghindari error gspread
        for col in df.select_dtypes(include=['datetime64[ns]', 'datetime64[ns, UTC]']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Pastikan kolom sesuai urutan di TAB_CONFIG
        if worksheet_name in TAB_CONFIG:
            df = df[TAB_CONFIG[worksheet_name]]
            
        set_with_dataframe(worksheet, df, resize=True)
        st.cache_data.clear() # Hapus semua cache agar data baru dimuat
    except Exception as e:
        st.error(f"Gagal memperbarui '{worksheet_name}': {e}")
        st.info("Pastikan urutan kolom di GSheet Anda sama dengan di TAB_CONFIG atau hapus tab GSheet agar dibuat ulang otomatis.")

# =======================================================================
# FUNGSI UTILITAS
# =======================================================================
def get_next_id(df, id_column, prefix):
    """Menghasilkan ID unik berikutnya."""
    if df.empty or id_column not in df.columns or df[id_column].isnull().all():
        return f"{prefix}-1"
    
    numeric_ids = pd.to_numeric(df[id_column].astype(str).str.replace(f'{prefix}-', ''), errors='coerce')
    numeric_ids = numeric_ids.dropna()
    
    if numeric_ids.empty:
        return f"{prefix}-1"
    
    return f"{prefix}-{int(numeric_ids.max()) + 1}"

def to_excel(df):
    """Mengonversi DataFrame ke file Excel di memori."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Laporan')
    processed_data = output.getvalue()
    return processed_data

# =======================================================================
# MAIN APP EXECUTION
# =======================================================================

# 1. Hubungkan ke Google Sheet
sh = connect_to_gsheet()

# 2. Inisialisasi Database (jika perlu)
initialize_database(sh)

# 3. Navigasi Sidebar (Req Poin 9) - UPDATE v3.2: Hapus 'Formulir Input Data'
st.sidebar.title("Navigasi Menu Evodia")
page = st.sidebar.radio(
    "Pilih Halaman:",
    ("Dashboard", "Stok & Material", "Manajemen Data (CRUD)", "Laporan & Editor Data"),
    key="menu_navigation"
)

# =======================================================================
# FUNGSI UNTUK MEMUAT DATA MASTER (FIX ERROR)
# =======================================================================
def load_master_data():
    """Memuat semua data master untuk dropdown dan formulir. Dibuat robust."""
    data = {
        "bom_df": pd.DataFrame(columns=TAB_CONFIG["products_bom"]),
        "inventory_df": pd.DataFrame(columns=TAB_CONFIG["inventory_stock"]),
        "product_list": [""],
        "supplier_list": [""],
        "material_list": [""]
    }
    
    try:
        # Muat data BOM
        bom_df = load_data("products_bom")
        if not bom_df.empty and 'product_name' in bom_df.columns:
            data["product_list"] = [""] + bom_df['product_name'].dropna().unique().tolist()
        data["bom_df"] = bom_df

        # Muat data Inventaris
        inventory_df = load_data("inventory_stock")
        if not inventory_df.empty:
            if 'supplier_name' in inventory_df.columns:
                data["supplier_list"] = [""] + inventory_df['supplier_name'].dropna().unique().tolist()
            if 'material_name' in inventory_df.columns:
                data["material_list"] = [""] + inventory_df['material_name'].dropna().unique().tolist()
        data["inventory_df"] = inventory_df
        
        return data

    except Exception as e:
        # Ini akan menangkap error jika load_data gagal total
        st.error(f"Gagal memuat data master: {e}")
        return data # Kembalikan data kosong agar aplikasi tidak crash

# Muat data master sekali di awal
master_data = load_master_data()
bom_df = master_data["bom_df"]
inventory_df = master_data["inventory_df"]
product_list = master_data["product_list"]
supplier_list = master_data["supplier_list"]
material_list = master_data["material_list"]

# =======================================================================
# HALAMAN: DASHBOARD (Req Poin 6.1)
# =======================================================================
if page == "Dashboard":
    st.header("Dashboard Utama")
    st.subheader("Ringkasan Bisnis")
    st.markdown("Halaman ini akan berisi metrik kunci dan ringkasan visual bisnis Anda.")
    
    col1, col2, col3 = st.columns(3)
    try:
        sales_df = load_data("sales_orders")
        col1.metric("Total Penjualan Tercatat", f"{len(sales_df)} Pesanan")
    except Exception:
        col1.metric("Total Penjualan Tercatat", "Error")
        
    col2.metric("Total Item Bahan Baku", f"{len(inventory_df)} SKU")
    
    try:
        purchase_df = load_data("purchase_orders")
        col3.metric("Total Pembelian Tercatat", f"{len(purchase_df)} Transaksi")
    except Exception:
        col3.metric("Total Pembelian Tercatat", "Error")


# =======================================================================
# HALAMAN: FORMULIR INPUT DATA (Req Poin 6.2) - DIHAPUS DI v3.2
# =======================================================================
# Halaman ini tidak lagi ada. Logika form dipindahkan ke
# halaman 'Stok & Material' dan 'Laporan & Editor Data'
# menggunakan st.dialog (popup)


# =======================================================================
# HALAMAN: STOK & MATERIAL (Req Poin 5) - UPDATE v3.2
# =======================================================================
elif page == "Stok & Material":
    st.header("Inventaris Stok Bahan Baku")
    st.info("Gunakan halaman ini untuk melihat dan memfilter stok. Untuk mengedit, gunakan halaman 'Manajemen Data (CRUD)'.")

    # --- FITUR BARU v3.2: Tombol Popup Produksi Internal ---
    if st.button("Produksi Internal Baru", type="primary"):
        # Reset data form (jika perlu, tapi form ini simpel)
        
        with st.dialog("Formulir Produksi Internal"):
            st.subheader("Formulir Produksi Internal")
            st.info("Gunakan form ini jika Anda memproduksi stok produk jadi tanpa ada penjualan langsung. Ini hanya akan mengurangi stok bahan baku.")
            
            if len(product_list) <= 1:
                st.warning("Data produk ('products_bom') masih kosong. Harap isi data produk terlebih dahulu di halaman 'Manajemen Data (CRUD)' sebelum mencatat produksi.")
            
            # Pindahkan Form Produksi ke dalam dialog
            with st.form("internal_production_form", clear_on_submit=True):
                product_name = st.selectbox("Produk yang Akan Diproduksi", product_list, key="prod_int_product")
                quantity_to_produce = st.number_input("Jumlah (Quantity) Produksi", min_value=1, value=1)
                
                submitted = st.form_submit_button("Produksi & Kurangi Bahan Baku")
                
                if submitted:
                    if not product_name:
                        st.error("Harap pilih produk.")
                    elif len(product_list) <= 1:
                        st.error("Tidak bisa produksi. Data produk masih kosong.")
                    else:
                        with st.spinner(f"Memproses produksi {product_name}...") as status_spinner:
                            try:
                                # (Logika backend tidak berubah)
                                recipe_row = bom_df[bom_df['product_name'] == product_name]
                                if recipe_row.empty:
                                    st.error(f"Resep untuk produk '{product_name}' tidak ditemukan."); st.stop()
                                
                                components = json.loads(recipe_row.iloc[0]['components'])
                                sufficient_stock = True
                                stock_updates = []
                                inventory_df_copy = inventory_df.copy()
                                
                                for item in components:
                                    material = item['material_name']; supplier = item['supplier_name']
                                    needed = item['quantity_needed'] * quantity_to_produce
                                    mask = (inventory_df_copy['material_name'] == material) & \
                                           (inventory_df_copy['supplier_name'] == supplier)
                                    
                                    if not mask.any():
                                        st.error(f"Bahan baku '{material}' (Supp: {supplier}) tidak ditemukan."); sufficient_stock = False; break
                                    
                                    stock_idx = inventory_df_copy[mask].index[0]
                                    current_stock = inventory_df_copy.loc[stock_idx, 'current_stock']
                                    
                                    if current_stock < needed:
                                        st.error(f"Stok tidak cukup untuk '{material}'. Dibutuhkan: {needed}, Tersedia: {current_stock}"); sufficient_stock = False; break
                                    else:
                                        stock_updates.append((stock_idx, current_stock - needed))

                                if sufficient_stock:
                                    for idx, new_val in stock_updates:
                                        inventory_df_copy.loc[idx, 'current_stock'] = new_val
                                    
                                    update_worksheet("inventory_stock", inventory_df_copy)
                                    st.cache_data.clear()
                                    st.success(f"Produksi internal {quantity_to_produce} pcs '{product_name}' berhasil! Stok bahan baku telah dikurangi.")
                                    st.rerun() # Tutup dialog dan refresh

                            except json.JSONDecodeError:
                                st.error(f"Gagal memproses resep untuk '{product_name}'. Format JSON di 'products_bom' salah.")
                            except Exception as e:
                                st.error(f"Terjadi kesalahan saat memproses produksi: {e}")

    # Tampilkan sisa halaman (data stok)
    st.markdown("---") # Pemisah
    if inventory_df.empty:
        st.info("Belum ada data di 'inventory_stock'. Silakan lakukan pembelian pertama.")
    else:
        search_term = st.text_input("Cari Material atau Supplier:", placeholder="Ketik untuk memfilter...")
        
        if search_term:
            filtered_df = inventory_df[
                inventory_df['material_name'].astype(str).str.contains(search_term, case=False, na=False) |
                inventory_df['supplier_name'].astype(str).str.contains(search_term, case=False, na=False)
            ]
        else:
            filtered_df = inventory_df.copy()
        
        low_stock_threshold = st.number_input("Tandai stok rendah di bawah:", min_value=0, value=10)
        
        def style_low_stock(row):
            if 'current_stock' in row:
                try:
                    if float(row['current_stock']) <= low_stock_threshold:
                        return ['background-color: #FFCCCB'] * len(row)
                except (ValueError, TypeError): pass
            return [''] * len(row)

        st.dataframe(
            filtered_df.style.apply(style_low_stock, axis=1),
            use_container_width=True
        )

# =======================================================================
# HALAMAN: LAPORAN & EDITOR DATA (Req Poin 8, 10) - UPDATE v3.2
# =======================================================================
elif page == "Laporan & Editor Data":
    st.header("Laporan & Editor Data (Penjualan & Pembelian)")
    
    data_source = st.selectbox("Pilih Sumber Data:", ["Laporan Penjualan (sales_orders)", "Laporan Pembelian (purchase_orders)"])
    tab_name = "sales_orders" if data_source.startswith("Laporan Penjualan") else "purchase_orders"
    
    # --- FITUR BARU v3.2: Tombol Popup Tambah Data ---
    if tab_name == "sales_orders":
        if st.button("Tambah Penjualan Baru", type="primary"):
            
            with st.dialog("Formulir Input Penjualan Baru"):
                st.subheader("Formulir Input Penjualan Baru")
                
                if len(product_list) <= 1:
                    st.warning("Data produk ('products_bom') masih kosong. Harap isi data produk terlebih dahulu di halaman 'Manajemen Data (CRUD)' sebelum mencatat penjualan.")
                
                # Pindahkan Form Penjualan ke dalam dialog
                with st.form("new_sale_form", clear_on_submit=True):
                    st.markdown("Masukkan detail penjualan baru. Stok akan otomatis berkurang.")
                    
                    col1, col2 = st.columns(2)
                    client_name = col1.text_input("Nama Klien", placeholder="Nama Klien/Customer")
                    status = col2.selectbox(
                        "Status Pesanan", 
                        ["Request", "Delivery", "Pending Payment", "Done"]
                    )
                    
                    product_name = col1.selectbox("Nama Produk", product_list)
                    product_quantity = col2.number_input("Jumlah (Quantity) Produk", min_value=1, value=1)
                    
                    total_purchase = col1.number_input("Total Pembelian (Rp)", min_value=0)
                    payment_method = col2.selectbox(
                        "Metode Pembayaran", 
                        ["Cash", "Transfer", "QRIS", "Marketplace", "Lainnya"]
                    )
                    
                    submitted = st.form_submit_button("Simpan Penjualan & Kurangi Stok")

                    if submitted:
                        if not all([client_name, product_name, product_quantity > 0]):
                            st.error("Harap isi semua field yang diperlukan (Klien, Produk, Quantity).")
                        elif len(product_list) <= 1:
                             st.error("Tidak bisa menyimpan penjualan. Data produk masih kosong.")
                        else:
                            with st.spinner(f"Memproses penjualan {product_name}...") as status_spinner:
                                try:
                                    # (Logika backend penjualan tidak berubah)
                                    recipe_row = bom_df[bom_df['product_name'] == product_name]
                                    if recipe_row.empty:
                                        st.error(f"Resep untuk produk '{product_name}' tidak ditemukan."); st.stop()
                                    
                                    components = json.loads(recipe_row.iloc[0]['components'])
                                    sufficient_stock = True
                                    stock_updates = []
                                    inventory_df_copy = inventory_df.copy()
                                    
                                    for item in components:
                                        material = item['material_name']; supplier = item['supplier_name']
                                        needed = item['quantity_needed'] * product_quantity
                                        mask = (inventory_df_copy['material_name'] == material) & \
                                               (inventory_df_copy['supplier_name'] == supplier)
                                        
                                        if not mask.any():
                                            st.error(f"Bahan baku '{material}' (Supp: {supplier}) tidak ditemukan."); sufficient_stock = False; break
                                        
                                        stock_idx = inventory_df_copy[mask].index[0]
                                        current_stock = inventory_df_copy.loc[stock_idx, 'current_stock']
                                        
                                        if current_stock < needed:
                                            st.error(f"Stok tidak cukup untuk '{material}'. Dibutuhkan: {needed}, Tersedia: {current_stock}"); sufficient_stock = False; break
                                        else:
                                            stock_updates.append((stock_idx, current_stock - needed))

                                    if sufficient_stock:
                                        for idx, new_val in stock_updates:
                                            inventory_df_copy.loc[idx, 'current_stock'] = new_val
                                        
                                        update_worksheet("inventory_stock", inventory_df_copy)
                                        
                                        sales_ws = sh.worksheet("sales_orders")
                                        sales_df = load_data("sales_orders")
                                        next_id = get_next_id(sales_df, 'receipt_id', 'SALE')
                                        new_sale_row = [
                                            next_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                            client_name, product_name, int(product_quantity), 
                                            float(total_purchase), payment_method, status
                                        ]
                                        sales_ws.append_row(new_sale_row)
                                        
                                        st.cache_data.clear()
                                        st.success(f"Penjualan '{product_name}' ({product_quantity} pcs) berhasil disimpan!")
                                        st.rerun() # Tutup dialog dan refresh

                                except json.JSONDecodeError:
                                    st.error(f"Gagal memproses resep untuk '{product_name}'. Format JSON di 'products_bom' salah.")
                                except Exception as e:
                                    st.error(f"Terjadi kesalahan saat memproses penjualan: {e}")

    elif tab_name == "purchase_orders":
        if st.button("Tambah Pembelian Baru", type="primary"):
            # Reset form multi-item setiap kali tombol ditekan
            st.session_state.purchase_items = [{"Material Name": "", "Price": 0, "Quantity": 1, "Unit": "gr"}]
            
            with st.dialog("Formulir Input Pembelian Baru (Multi-Item)"):
                st.subheader("Formulir Input Pembelian Baru (Multi-Item)")
                st.markdown("Formulir ini memungkinkan Anda mencatat beberapa item dalam satu PO (Purchase Order).")

                # Inisialisasi state untuk data editor item (jika belum ada)
                if 'purchase_items' not in st.session_state:
                    st.session_state.purchase_items = [
                        {"Material Name": "", "Price": 0, "Quantity": 1, "Unit": "gr"}
                    ]

                col1, col2 = st.columns(2)
                supplier_name = col1.text_input("Nama Supplier", placeholder="cth: KIMIA MARKET (SHOPEE)", key="po_supplier")
                category_po = col2.selectbox(
                    "Category", 
                    ["", "Operational", "RnD", "Asset"],
                    key="po_category"
                )
                
                sub_category_po = ""
                if category_po in ["Operational", "RnD"]:
                    sub_category_po = col2.selectbox(
                        "Sub-Category", 
                        ["", "Bahan Baku", "Barang Kemas"],
                        key="po_subcategory"
                    )
                
                status_po = col1.selectbox("Status Pembayaran", ["Pending", "Paid"], key="po_status")
                payment_system = col2.selectbox("Sistem Pembayaran", ["Shopeepaylater", "Cash", "Transfer", "Marketplace"], key="po_payment")

                st.markdown("---")
                st.markdown("#### Items")
                
                # Data editor untuk multi-item (Sesuai Req Gambar)
                edited_items = st.data_editor(
                    st.session_state.purchase_items,
                    num_rows="dynamic",
                    column_config={
                        "Material Name": st.column_config.TextColumn("Material Name", required=True),
                        "Price": st.column_config.NumberColumn("Total Price (Rp)", min_value=0, required=True),
                        "Quantity": st.column_config.NumberColumn("Quantity", min_value=0.01, format="%.2f", required=True),
                        "Unit": st.column_config.TextColumn("Unit", required=True, help="cth: gr, ml, pcs"),
                    },
                    key="purchase_items_editor"
                )
                
                if st.button("Simpan Pembelian & Tambah Stok", key="po_submit"):
                    if not supplier_name or not category_po or not status_po:
                        st.error("Harap isi field utama (Supplier, Category, Status).")
                    elif category_po in ["Operational", "RnD"] and not sub_category_po:
                        st.error("Harap isi Sub-Category untuk Operational atau RnD.")
                    elif not edited_items or all(item['Material Name'] == "" for item in edited_items):
                        st.error("Harap tambahkan setidaknya satu item pembelian.")
                    else:
                        with st.spinner("Memproses pembelian multi-item..."):
                            try:
                                # (Logika backend pembelian tidak berubah)
                                purchase_ws = sh.worksheet("purchase_orders")
                                purchase_df = load_data("purchase_orders")
                                inventory_df_copy = load_data("inventory_stock").copy()
                                
                                new_purchase_rows = []
                                items_processed = 0
                                
                                for item in edited_items:
                                    material_name = item.get("Material Name")
                                    quantity = float(item.get("Quantity", 0))
                                    unit = item.get("Unit")
                                    price = float(item.get("Price", 0))

                                    if not material_name or quantity <= 0 or not unit:
                                        st.warning(f"Melewatkan item '{material_name}' karena data tidak lengkap.")
                                        continue

                                    next_id = get_next_id(purchase_df, 'purchase_id', 'PO')
                                    new_row_data = {
                                        "purchase_id": next_id,
                                        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        "category": category_po,
                                        "sub_category": sub_category_po,
                                        "supplier_name": supplier_name,
                                        "material_name": material_name,
                                        "quantity": quantity,
                                        "unit_of_measure": unit,
                                        "price": price,
                                        "payment_system": payment_system,
                                        "status": status_po
                                    }
                                    new_purchase_rows.append(list(new_row_data.values()))
                                    
                                    purchase_df.loc[len(purchase_df)] = new_row_data

                                    mask = (inventory_df_copy['material_name'] == material_name) & \
                                           (inventory_df_copy['supplier_name'] == supplier_name)
                                    
                                    if mask.any():
                                        stock_idx = inventory_df_copy[mask].index[0]
                                        current_stock = inventory_df_copy.loc[stock_idx, 'current_stock']
                                        inventory_df_copy.loc[stock_idx, 'current_stock'] = current_stock + quantity
                                    else:
                                        next_mat_id = get_next_id(inventory_df_copy, 'material_id', 'MAT')
                                        new_mat_row = {
                                            "material_id": next_mat_id,
                                            "material_name": material_name,
                                            "supplier_name": supplier_name,
                                            "category": "Bahan Baku" if sub_category_po == "Bahan Baku" else "Kemasan",
                                            "current_stock": quantity,
                                            "unit_of_measure": unit
                                        }
                                        inventory_df_copy.loc[len(inventory_df_copy)] = new_mat_row
                                    
                                    items_processed += 1
                                
                                if items_processed > 0:
                                    purchase_ws.append_rows(new_purchase_rows)
                                    update_worksheet("inventory_stock", inventory_df_copy)
                                    
                                    st.cache_data.clear()
                                    st.success(f"Pembelian berhasil disimpan! {items_processed} item diproses dan stok telah diperbarui.")
                                    st.rerun() # Tutup dialog dan refresh
                                else:
                                    st.error("Tidak ada item yang valid untuk diproses.")
                                    
                            except Exception as e:
                                st.error(f"Terjadi kesalahan saat memproses pembelian: {e}")
    
    st.markdown("---") # Pemisah
    try:
        all_data_df = load_data(tab_name)
        
        if 'date' not in all_data_df.columns or all_data_df.empty:
            st.info(f"Belum ada data di '{tab_name}' atau kolom 'date' tidak ditemukan.")
        else:
            all_data_df['date'] = pd.to_datetime(all_data_df['date'], errors='coerce')
            all_data_df = all_data_df.dropna(subset=['date'])

            st.subheader("Filter Data")
            col1, col2 = st.columns(2)
            min_date = all_data_df['date'].min().date()
            max_date = all_data_df['date'].max().date()
            
            start_date = col1.date_input("Dari Tanggal", min_date, min_value=min_date, max_value=max_date)
            end_date = col2.date_input("Sampai Tanggal", max_date, min_value=min_date, max_value=max_date)
            
            if start_date > end_date:
                st.error("Tanggal mulai tidak boleh melebihi tanggal akhir.")
            else:
                start_datetime = pd.to_datetime(start_date)
                end_datetime = pd.to_datetime(end_date) + pd.Timedelta(days=1)
                
                filtered_df = all_data_df[
                    (all_data_df['date'] >= start_datetime) &
                    (all_data_df['date'] < end_datetime)
                ].copy()
                
                st.subheader(f"Editor Data untuk: {tab_name}")
                st.markdown("Anda dapat mengedit data di tabel ini (misalnya memperbaiki typo). **Perhatian:** Mengedit data di sini TIDAK akan mengubah data stok.")
                
                edited_df = st.data_editor(
                    filtered_df, 
                    use_container_width=True, 
                    num_rows="dynamic",
                    disabled=[col for col in filtered_df.columns if '_id' in col or 'date' in col],
                    key=f"editor_{tab_name}"
                )
                
                if st.button("Simpan Perubahan ke Google Sheet"):
                    with st.spinner("Menyimpan perubahan..."):
                        # Menggabungkan data yang diedit kembali ke data lengkap
                        all_data_df.update(edited_df)
                        update_worksheet(tab_name, all_data_df)
                        st.success("Perubahan berhasil disimpan!")
                        st.rerun()

                st.subheader("Unduh Laporan (XLSX)")
                excel_data = to_excel(edited_df)
                st.download_button(
                    label="📥 Unduh Laporan .xlsx",
                    data=excel_data,
                    file_name=f"laporan_{tab_name}_{start_date}_to_{end_date}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

    except Exception as e:
        st.error(f"Gagal memuat halaman laporan: {e}")


