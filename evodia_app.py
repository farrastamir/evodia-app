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
    layout="wide"
)

# Judul utama aplikasi
st.title("🌿 Aplikasi Manajemen Bisnis Evodia v3.0")

# Ambil konfigurasi dari st.secrets
try:
    GCP_CREDS = st.secrets["gcp_service_account"]
    SHEET_URL = st.secrets["google_sheet"]["url"]
except (KeyError, FileNotFoundError):
    st.error("⚠️ Gagal memuat file 'secrets.toml'. Pastikan Anda telah mengikuti `setup_instructions.md` dengan benar.")
    st.stop()

# Definisikan nama-nama tab dan kolomnya sesuai PRD
TAB_CONFIG = {
    "sales_orders": [
        "receipt_id", "date", "client_name", "product_name", 
        "product_quantity", "total_purchase", "payment_method", "status"
    ],
    "purchase_orders": [
        "purchase_id", "date", "category", "type_of_materials", 
        "supplier_id", "supplier_name", "material_name", "quantity", 
        "unit_of_measure", "price", "payment_system", "status"
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
# GAYA / STYLING (CSS - Req Poin 1)
# =======================================================================
# Menerapkan skema warna kustom dari PRD
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
    }}
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {{
        color: white; /* Warna label opsi radio */
    }}

    /* Tombol Aksi */
    div[data-testid="stButton"] > button,
    div[data-testid="stFormSubmitButton"] > button {{
        background-color: #FF69B4; /* HotPink */
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
    }}
    div[data-testid="stButton"] > button:hover,
    div[data-testid="stFormSubmitButton"] > button:hover {{
        background-color: #FF1493; /* DeepPink (hover) */
        color: white;
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
        # Pastikan GCP_CREDS adalah dict, jika tidak, parse dari JSON string
        if isinstance(GCP_CREDS, str):
            creds_dict = json.loads(GCP_CREDS)
        else:
            creds_dict = dict(GCP_CREDS)
            
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(SHEET_URL)
        return spreadsheet
    except Exception as e:
        st.error(f"Gagal terhubung ke Google Sheets: {e}")
        st.stop()

@st.cache_data(ttl=600) # Cache data selama 10 menit
def load_data(worksheet_name):
    """Memuat data dari tab tertentu ke dalam Pandas DataFrame."""
    try:
        worksheet = sh.worksheet(worksheet_name)
        # Menggunakan header=0 untuk mengambil baris pertama sebagai header
        df = get_as_dataframe(worksheet, header=0, parse_dates=True, usecols=lambda x: x not in ['', None])
        # Membersihkan kolom yang mungkin kosong
        df = df.dropna(axis=1, how='all')
        
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
        return pd.DataFrame()

def initialize_database(spreadsheet):
    """Memeriksa apakah semua tab yang diperlukan ada, jika tidak, buat tab tersebut."""
    existing_tabs = [ws.title for ws in spreadsheet.worksheets()]
    setup_performed = False
    
    with st.spinner("Memeriksa integritas database (Google Sheets)..."):
        for tab_name, headers in TAB_CONFIG.items():
            if tab_name not in existing_tabs:
                st.warning(f"Tab '{tab_name}' tidak ditemukan. Membuat tab baru...")
                try:
                    # Buat worksheet baru
                    new_ws = spreadsheet.add_worksheet(title=tab_name, rows=100, cols=len(headers))
                    # Tambahkan baris header
                    new_ws.append_row(headers)
                    st.success(f"Tab '{tab_name}' berhasil dibuat dengan header.")
                    setup_performed = True
                except Exception as e:
                    st.error(f"Gagal membuat tab '{tab_name}': {e}")
    
    if setup_performed:
        st.success("Inisialisasi database selesai. Harap refresh halaman.")
        st.stop()

def update_worksheet(worksheet_name, df):
    """Menulis ulang seluruh worksheet dengan data dari DataFrame."""
    try:
        worksheet = sh.worksheet(worksheet_name)
        set_with_dataframe(worksheet, df, resize=True)
        # Hapus cache untuk data ini agar data baru dimuat
        load_data.clear()
    except Exception as e:
        st.error(f"Gagal memperbarui '{worksheet_name}': {e}")

# =======================================================================
# FUNGSI UTILITAS
# =======================================================================
def get_next_id(df, id_column):
    """Menghasilkan ID unik berikutnya."""
    if df.empty or id_column not in df.columns or df[id_column].isnull().all():
        return 1
    
    # Ekstrak angka dari ID
    numeric_ids = pd.to_numeric(df[id_column].astype(str).str.extract(r'(\d+)', expand=False), errors='coerce')
    numeric_ids = numeric_ids.dropna()
    
    if numeric_ids.empty:
        return 1
    
    return int(numeric_ids.max()) + 1

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

# 3. Navigasi Sidebar (Req Poin 9)
st.sidebar.title("Navigasi Menu Evodia")
page = st.sidebar.radio(
    "Pilih Halaman:",
    ("Dashboard", "Formulir Input Data", "Stok & Material", "Data Mentah & Laporan")
)

# =======================================================================
# HALAMAN: DASHBOARD (Req Poin 6.1)
# =======================================================================
if page == "Dashboard":
    st.header("Dashboard Utama")
    st.subheader("Ringkasan Bisnis")
    st.markdown("Halaman ini akan berisi metrik kunci dan ringkasan visual bisnis Anda.")
    st.info("Fitur dashboard akan dikembangkan di versi selanjutnya.")

    st.subheader("Data Sekilas")
    col1, col2, col3 = st.columns(3)
    try:
        sales_df = load_data("sales_orders")
        inventory_df = load_data("inventory_stock")
        purchase_df = load_data("purchase_orders")

        col1.metric("Total Penjualan Tercatat", f"{len(sales_df)} Pesanan")
        col2.metric("Total Item Bahan Baku", f"{len(inventory_df)} SKU")
        col3.metric("Total Pembelian Tercatat", f"{len(purchase_df)} Transaksi")
    except Exception:
        st.warning("Gagal memuat data ringkasan. Pastikan tab GSheets sudah terisi.")


# =======================================================================
# HALAMAN: FORMULIR INPUT DATA (Req Poin 6.2)
# =======================================================================
elif page == "Formulir Input Data":
    st.header("Formulir Input Data")
    
    # Muat data yang diperlukan untuk dropdown
    try:
        bom_df = load_data("products_bom")
        inventory_df = load_data("inventory_stock")
        
        product_list = [""] + bom_df['product_name'].tolist()
        supplier_list = [""] + inventory_df['supplier_name'].unique().tolist()
        material_list = [""] + inventory_df['material_name'].unique().tolist()
    except Exception as e:
        st.error(f"Gagal memuat data master untuk formulir: {e}")
        st.stop()

    tab_sales, tab_purchase, tab_recipe, tab_production = st.tabs([
        "Form: Input Penjualan Baru", 
        "Form: Input Pembelian Baru", 
        "Form: Editor Resep/Produk", 
        "Form: Produksi Internal"
    ])

    # --- 1. Form Input Penjualan Baru (Req Poin 3 & 7) ---
    with tab_sales:
        st.subheader("Formulir Input Penjualan Baru")
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
                else:
                    with st.spinner(f"Memproses penjualan {product_name}...") as status_spinner:
                        try:
                            # 1. Dapatkan resep
                            recipe_row = bom_df[bom_df['product_name'] == product_name]
                            if recipe_row.empty:
                                st.error(f"Resep untuk produk '{product_name}' tidak ditemukan di tab 'products_bom'.")
                                st.stop()
                            
                            components_json = recipe_row.iloc[0]['components']
                            components = json.loads(components_json)
                            
                            # 2. Cek stok
                            sufficient_stock = True
                            stock_updates = [] # (index, new_stock)
                            inventory_df_copy = inventory_df.copy() # Bekerja pada salinan
                            
                            for item in components:
                                material = item['material_name']
                                supplier = item['supplier_name']
                                needed = item['quantity_needed'] * product_quantity
                                
                                # Cari stok di DataFrame
                                mask = (inventory_df_copy['material_name'] == material) & \
                                       (inventory_df_copy['supplier_name'] == supplier)
                                
                                if not mask.any():
                                    st.error(f"Bahan baku '{material}' dari supplier '{supplier}' tidak ditemukan di 'inventory_stock'.")
                                    sufficient_stock = False
                                    break
                                
                                stock_idx = inventory_df_copy[mask].index[0]
                                current_stock = inventory_df_copy.loc[stock_idx, 'current_stock']
                                
                                if current_stock < needed:
                                    st.error(f"Stok tidak cukup untuk '{material}' (Supplier: {supplier}). Dibutuhkan: {needed}, Tersedia: {current_stock}")
                                    sufficient_stock = False
                                    break
                                else:
                                    # Simpan pembaruan untuk nanti
                                    new_stock_val = current_stock - needed
                                    stock_updates.append((stock_idx, new_stock_val))

                            # 3. Jika stok cukup, proses transaksi
                            if sufficient_stock:
                                # a. Terapkan pembaruan stok ke DataFrame
                                for idx, new_val in stock_updates:
                                    inventory_df_copy.loc[idx, 'current_stock'] = new_val
                                
                                # b. Tulis pembaruan stok ke Google Sheet
                                update_worksheet("inventory_stock", inventory_df_copy)
                                
                                # c. Tambahkan data penjualan ke Google Sheet
                                sales_ws = sh.worksheet("sales_orders")
                                sales_df = load_data("sales_orders") # Muat data terbaru untuk ID
                                next_id = f"EVO-S-{get_next_id(sales_df, 'receipt_id'):04d}"
                                new_sale_row = [
                                    next_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    client_name, product_name, int(product_quantity), 
                                    float(total_purchase), payment_method, status
                                ]
                                sales_ws.append_row(new_sale_row)
                                
                                load_data.clear() # Hapus semua cache
                                st.success(f"Penjualan '{product_name}' ({product_quantity} pcs) berhasil disimpan! Stok bahan baku telah diperbarui.")

                        except Exception as e:
                            st.error(f"Terjadi kesalahan saat memproses penjualan: {e}")

    # --- 2. Form Input Pembelian Baru (Req Poin 4 & 7) ---
    with tab_purchase:
        st.subheader("Formulir Input Pembelian Baru")
        with st.form("new_purchase_form", clear_on_submit=True):
            st.markdown("Masukkan detail pembelian bahan baku. Stok akan otomatis bertambah.")
            
            c1, c2, c3 = st.columns(3)
            supplier_name = c1.text_input("Nama Supplier", placeholder="cth: KIMIA MARKET (SHOPEE)")
            material_name = c2.text_input("Nama Material", placeholder="cth: Methanol")
            quantity = c3.number_input("Jumlah (Quantity)", min_value=0.0, format="%.2f")
            unit = c1.text_input("Satuan (UoM)", placeholder="cth: ml, gr, pcs")
            price = c2.number_input("Harga Total Pembelian", min_value=0)
            
            category_po = c3.selectbox(
                "Kategori Pembelian", 
                ["Asset", "Operational", "Development"]
            )
            type_of_materials = c1.text_input("Tipe Material", placeholder="cth: Solvent, Fragrance")
            payment_system = c2.selectbox("Sistem Pembayaran", ["Cash", "Transfer", "Marketplace"])
            status_po = c3.selectbox("Status Pembayaran", ["Paid", "Pending"])
            
            # Kategori ini untuk master stok (inventory_stock)
            category_stock = st.selectbox(
                "Kategori Stok (Untuk Master Inventaris)", 
                ["Bahan Baku", "Aset", "Kemasan"],
                help="Pilih kategori untuk material ini di master stok. Jika material baru, ini akan digunakan."
            )
            
            submitted = st.form_submit_button("Simpan Pembelian & Tambah Stok")

            if submitted:
                if not all([supplier_name, material_name, quantity > 0, unit]):
                    st.error("Harap isi semua field utama (Supplier, Material, Quantity, Satuan).")
                else:
                    with st.spinner("Memproses pembelian...") as status_spinner:
                        try:
                            # 1. Tambahkan data pembelian ke 'purchase_orders'
                            purchase_ws = sh.worksheet("purchase_orders")
                            purchase_df = load_data("purchase_orders") # Muat data terbaru untuk ID
                            next_id = f"EVO-P-{get_next_id(purchase_df, 'purchase_id'):04d}"
                            
                            new_purchase_row = [
                                next_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                category_po, type_of_materials, "", supplier_name,
                                material_name, float(quantity), unit, float(price),
                                payment_system, status_po
                            ]
                            purchase_ws.append_row(new_purchase_row)
                            
                            # 2. Perbarui 'inventory_stock'
                            inventory_df_copy = inventory_df.copy() # Muat salinan terbaru
                            
                            mask = (inventory_df_copy['material_name'] == material_name) & \
                                   (inventory_df_copy['supplier_name'] == supplier_name)
                            
                            if mask.any():
                                # Jika material ditemukan: Tambah stok
                                stock_idx = inventory_df_copy[mask].index[0]
                                current_stock = inventory_df_copy.loc[stock_idx, 'current_stock']
                                inventory_df_copy.loc[stock_idx, 'current_stock'] = current_stock + float(quantity)
                                
                                status_spinner.update(label=f"Stok '{material_name}' ditemukan. Menambahkan {quantity}...")
                            else:
                                # Jika material tidak ditemukan: Buat entri baru
                                next_mat_id = f"MAT-{get_next_id(inventory_df_copy, 'material_id'):04d}"
                                new_material_data = {
                                    "material_id": next_mat_id,
                                    "material_name": material_name,
                                    "supplier_name": supplier_name,
                                    "category": category_stock,
                                    "current_stock": float(quantity),
                                    "unit_of_measure": unit
                                }
                                # Pastikan kolomnya sesuai
                                new_row_df = pd.DataFrame([new_material_data], columns=TAB_CONFIG["inventory_stock"])
                                inventory_df_copy = pd.concat([inventory_df_copy, new_row_df], ignore_index=True)
                                
                                status_spinner.update(label=f"Material baru '{material_name}' ditambahkan ke stok...")

                            # 3. Tulis kembali ke Google Sheet
                            update_worksheet("inventory_stock", inventory_df_copy)
                            
                            load_data.clear() # Hapus semua cache
                            st.success(f"Pembelian '{material_name}' ({quantity} {unit}) berhasil disimpan! Stok telah diperbarui.")
                            
                        except Exception as e:
                            st.error(f"Terjadi kesalahan saat memproses pembelian: {e}")
    
    # --- 3. Form Editor Resep/Produk (Req Poin 6) ---
    with tab_recipe:
        st.subheader("Editor Resep (Bill of Materials)")
        
        product_to_edit = st.selectbox(
            "Pilih Produk untuk Diedit",
            ["--- Buat Produk Baru ---"] + bom_df['product_name'].tolist()
        )
        
        current_components_data = []
        product_name_input = ""
        
        if product_to_edit == "--- Buat Produk Baru ---":
            st.markdown("#### Membuat Produk Baru")
            product_name_input = st.text_input("Nama Produk Baru", key="new_prod_name")
            st.markdown("Tambahkan komponen resep di bawah ini:")
            current_components_data = [
                {"material_name": "Contoh Material", "supplier_name": "Contoh Supplier", "quantity_needed": 10}
            ]
        else:
            st.markdown(f"#### Mengedit Produk: {product_to_edit}")
            product_name_input = product_to_edit
            try:
                recipe_row = bom_df[bom_df['product_name'] == product_to_edit].iloc[0]
                current_components_data = json.loads(recipe_row['components'])
            except Exception as e:
                st.error(f"Gagal memuat resep. Pastikan format JSON di GSheet benar. Error: {e}")
                current_components_data = []

        # Editor Resep (Req Poin 6)
        st.markdown("**Editor Komponen Resep:**")
        edited_components = st.data_editor(
            current_components_data,
            num_rows="dynamic",
            column_config={
                "material_name": st.column_config.SelectboxColumn("Material", options=material_list, required=True),
                "supplier_name": st.column_config.SelectboxColumn("Supplier", options=supplier_list, required=True),
                "quantity_needed": st.column_config.NumberColumn("Jumlah Dibutuhkan", min_value=0, format="%.2f", required=True)
            },
            key=f"editor_{product_to_edit}" # Key unik agar editor di-reset saat produk ganti
        )
        
        if st.button("Simpan Resep"):
            if not product_name_input:
                st.error("Nama produk tidak boleh kosong.")
            elif not edited_components:
                st.error("Resep tidak boleh kosong.")
            else:
                with st.spinner(f"Menyimpan resep untuk '{product_name_input}'..."):
                    try:
                        bom_df_copy = bom_df.copy()
                        new_json_components = json.dumps(edited_components)
                        
                        if product_to_edit == "--- Buat Produk Baru ---":
                            # Tambah baris baru
                            new_row_data = {
                                "product_name": product_name_input,
                                "components": new_json_components
                            }
                            new_row_df = pd.DataFrame([new_row_data], columns=TAB_CONFIG["products_bom"])
                            bom_df_copy = pd.concat([bom_df_copy, new_row_df], ignore_index=True)
                        else:
                            # Update baris yang ada
                            mask = bom_df_copy['product_name'] == product_to_edit
                            bom_df_copy.loc[mask, 'components'] = new_json_components
                        
                        update_worksheet("products_bom", bom_df_copy)
                        load_data.clear()
                        st.success(f"Resep untuk '{product_name_input}' berhasil disimpan!")
                        st.rerun() # Refresh halaman untuk update dropdown
                        
                    except Exception as e:
                        st.error(f"Gagal menyimpan resep: {e}")

    # --- 4. Form Produksi Internal (Req Poin 7) ---
    with tab_production:
        st.subheader("Formulir Produksi Internal")
        st.info("Gunakan form ini jika Anda memproduksi stok produk jadi tanpa ada penjualan langsung. Ini hanya akan mengurangi stok bahan baku.")
        
        with st.form("internal_production_form", clear_on_submit=True):
            product_name = st.selectbox("Produk yang Akan Diproduksi", product_list)
            quantity_to_produce = st.number_input("Jumlah (Quantity) Produksi", min_value=1, value=1)
            
            submitted = st.form_submit_button("Produksi ke Stok & Kurangi Bahan Baku")
            
            if submitted:
                if not product_name:
                    st.error("Harap pilih produk.")
                else:
                    # Logika ini SAMA DENGAN PENJUALAN, hanya tanpa menyimpan ke 'sales_orders'
                    with st.spinner(f"Memproses produksi {product_name}...") as status_spinner:
                        try:
                            # 1. Dapatkan resep
                            recipe_row = bom_df[bom_df['product_name'] == product_name]
                            if recipe_row.empty:
                                st.error(f"Resep untuk produk '{product_name}' tidak ditemukan.")
                                st.stop()
                            
                            components = json.loads(recipe_row.iloc[0]['components'])
                            
                            # 2. Cek stok
                            sufficient_stock = True
                            stock_updates = []
                            inventory_df_copy = inventory_df.copy()
                            
                            for item in components:
                                material = item['material_name']
                                supplier = item['supplier_name']
                                needed = item['quantity_needed'] * quantity_to_produce
                                
                                mask = (inventory_df_copy['material_name'] == material) & \
                                       (inventory_df_copy['supplier_name'] == supplier)
                                
                                if not mask.any():
                                    st.error(f"Bahan baku '{material}' (Supplier: {supplier}) tidak ditemukan.")
                                    sufficient_stock = False
                                    break
                                
                                stock_idx = inventory_df_copy[mask].index[0]
                                current_stock = inventory_df_copy.loc[stock_idx, 'current_stock']
                                
                                if current_stock < needed:
                                    st.error(f"Stok tidak cukup untuk '{material}'. Dibutuhkan: {needed}, Tersedia: {current_stock}")
                                    sufficient_stock = False
                                    break
                                else:
                                    new_stock_val = current_stock - needed
                                    stock_updates.append((stock_idx, new_stock_val))

                            # 3. Jika stok cukup, proses
                            if sufficient_stock:
                                for idx, new_val in stock_updates:
                                    inventory_df_copy.loc[idx, 'current_stock'] = new_val
                                
                                update_worksheet("inventory_stock", inventory_df_copy)
                                
                                load_data.clear()
                                st.success(f"Produksi internal {quantity_to_produce} pcs '{product_name}' berhasil! Stok bahan baku telah dikurangi.")

                        except Exception as e:
                            st.error(f"Terjadi kesalahan saat memproses produksi: {e}")

# =======================================================================
# HALAMAN: STOK & MATERIAL (Req Poin 5)
# =======================================================================
elif page == "Stok & Material":
    st.header("Inventaris Stok Bahan Baku Saat Ini")
    
    try:
        inventory_df = load_data("inventory_stock")
        
        if inventory_df.empty:
            st.info("Belum ada data di 'inventory_stock'. Silakan lakukan pembelian pertama.")
        else:
            # Filter (Req Poin 5)
            search_term = st.text_input("Cari Material atau Supplier:", placeholder="Ketik untuk memfilter...")
            
            if search_term:
                filtered_df = inventory_df[
                    inventory_df['material_name'].str.contains(search_term, case=False, na=False) |
                    inventory_df['supplier_name'].str.contains(search_term, case=False, na=False)
                ]
            else:
                filtered_df = inventory_df.copy()
            
            # Peringatan stok rendah
            low_stock_threshold = st.number_input("Tandai stok rendah di bawah:", min_value=0, value=10)
            
            # Conditional Formatting (Req Poin 5)
            def style_low_stock(row):
                if 'current_stock' in row:
                    try:
                        if float(row['current_stock']) <= low_stock_threshold:
                            return ['background-color: #FFCCCB'] * len(row) # Merah muda
                    except (ValueError, TypeError):
                        pass
                return [''] * len(row)

            st.dataframe(
                filtered_df.style.apply(style_low_stock, axis=1),
                use_container_width=True
            )
            
            low_stock_items = filtered_df[filtered_df['current_stock'] <= low_stock_threshold]
            if not low_stock_items.empty:
                st.warning(f"**Peringatan Stok Rendah:** Ada {len(low_stock_items)} item yang berada di bawah atau sama dengan {low_stock_threshold} unit.")
                st.dataframe(low_stock_items[['material_name', 'supplier_name', 'current_stock', 'unit_of_measure']], use_container_width=True)

    except Exception as e:
        st.error(f"Gagal memuat data inventaris: {e}")

# =======================================================================
# HALAMAN: DATA MENTAH & LAPORAN (Req Poin 8, 10)
# =======================================================================
elif page == "Data Mentah & Laporan":
    st.header("Data Mentah, Editor & Laporan")
    
    data_source = st.selectbox("Pilih Sumber Data:", ["Laporan Penjualan (sales_orders)", "Laporan Pembelian (purchase_orders)"])
    tab_name = "sales_orders" if data_source.startswith("Laporan Penjualan") else "purchase_orders"
    
    try:
        all_data_df = load_data(tab_name)
        
        if 'date' not in all_data_df.columns:
            st.error(f"Kolom 'date' tidak ditemukan di tab '{tab_name}'. Filter tanggal tidak dapat digunakan.")
            st.dataframe(all_data_df, use_container_width=True)
        
        elif all_data_df.empty:
            st.info(f"Belum ada data di '{tab_name}'.")
        
        else:
            # Pastikan 'date' adalah datetime
            all_data_df['date'] = pd.to_datetime(all_data_df['date'], errors='coerce')
            all_data_df = all_data_df.dropna(subset=['date']) # Hapus baris dengan tanggal tidak valid

            # Filter Tanggal (Req Poin 8)
            st.subheader("Filter Data")
            col1, col2 = st.columns(2)
            min_date = all_data_df['date'].min().date()
            max_date = all_data_df['date'].max().date()
            
            start_date = col1.date_input("Dari Tanggal", min_date, min_value=min_date, max_value=max_date)
            end_date = col2.date_input("Sampai Tanggal", max_date, min_value=min_date, max_value=max_date)
            
            if start_date > end_date:
                st.error("Tanggal mulai tidak boleh melebihi tanggal akhir.")
            else:
                # Filter DataFrame
                start_datetime = pd.to_datetime(start_date)
                end_datetime = pd.to_datetime(end_date) + pd.Timedelta(days=1) # Sampai akhir hari
                
                filtered_df = all_data_df[
                    (all_data_df['date'] >= start_datetime) &
                    (all_data_df['date'] < end_datetime)
                ].copy() # Buat salinan untuk diedit
                
                st.subheader(f"Data Editor untuk: {tab_name}")
                st.markdown("Anda dapat mengedit data di tabel ini (misalnya memperbaiki typo). **Perhatian:** Perubahan ini akan menimpa data di Google Sheet.")
                
                # Data Editor (Req Poin 10)
                # Simpan indeks asli untuk proses 'update' nanti
                original_indices = filtered_df.index
                
                # Tampilkan data di editor
                edited_df = st.data_editor(
                    filtered_df, 
                    use_container_width=True, 
                    num_rows="dynamic",
                    # Nonaktifkan pengeditan kolom ID dan tanggal
                    disabled=["receipt_id", "purchase_id", "date"] 
                )
                
                if st.button("Simpan Perubahan ke Google Sheet"):
                    with st.spinner("Menyimpan perubahan..."):
                        try:
                            # 1. Buat salinan dari data asli (full)
                            all_data_updated = all_data_df.copy()
                            
                            # 2. Kembalikan indeks asli ke data yang diedit
                            edited_df.index = original_indices
                            
                            # 3. Gunakan .update() untuk menimpa perubahan dari edited_df ke all_data_updated
                            all_data_updated.update(edited_df)
                            
                            # 4. Tulis kembali SEMUA data ke Google Sheet
                            # Konversi 'date' kembali ke string agar gspread tidak error
                            all_data_updated['date'] = all_data_updated['date'].dt.strftime('%Y-%m-%d %H:%M:%S')
                            
                            update_worksheet(tab_name, all_data_updated)
                            
                            load_data.clear() # Hapus cache
                            st.success("Perubahan berhasil disimpan!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Gagal menyimpan perubahan: {e}")

                st.subheader("Unduh Laporan (XLSX)")
                st.markdown("Tombol di bawah ini akan mengunduh data yang **sudah Anda filter** sebagai file Excel.")
                
                # Download Button (Req Poin 8)
                excel_data = to_excel(edited_df) # Gunakan data yang sudah diedit/difilter
                st.download_button(
                    label="📥 Unduh Laporan .xlsx",
                    data=excel_data,
                    file_name=f"laporan_{tab_name}_{start_date}_to_{end_date}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

    except Exception as e:
        st.error(f"Gagal memuat halaman laporan: {e}")

