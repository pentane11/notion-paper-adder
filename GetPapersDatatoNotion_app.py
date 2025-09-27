import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import requests
from notion_client import Client
import re
import fitz  # PyMuPDF
import json
import os
import sys
from pathlib import Path

# --- アプリケーション設定 ---
APP_NAME = "NotionPaperAdder"

def get_config_path():
    """OSに応じた設定ファイルのパスを取得し、ディレクトリを準備する"""
    if sys.platform == "win32":
        app_dir = Path(os.getenv("APPDATA")) / APP_NAME
    elif sys.platform == "darwin":
        app_dir = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        app_dir = Path.home() / ".config" / APP_NAME
    
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir / "config.json"

CONFIG_FILE = get_config_path()

# --- 設定ファイル管理 ---
def save_config(api_key, db_id):
    """APIキーとDB IDをJSONファイルに保存する"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump({'api_key': api_key, 'db_id': db_id}, f, indent=4)

def load_config():
    """JSONファイルから設定を読み込む"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

# --- 論文処理のバックエンド関数 (変更なし) ---
def extract_doi_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        first_page_text = doc[0].get_text()
        doc.close()
        doi_pattern = r'10\.\d{4,9}/[-._;()/:A-Z0-9]+'
        match = re.search(doi_pattern, first_page_text, re.IGNORECASE)
        return match.group(0) if match else None
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return None

def check_if_paper_exists(doi, api_key, db_id):
    notion = Client(auth=api_key)
    try:
        query_filter = {"property": "URL", "url": {"contains": doi}}
        response = notion.databases.query(database_id=db_id, filter=query_filter)
        return len(response["results"]) > 0
    except Exception as e:
        print(f"Notion query error: {e}")
        return True

def get_paper_info_from_doi(doi):
    url = f"https://api.crossref.org/works/{doi}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()['message']
        title = data.get('title', ['No Title Found'])[0]
        authors_list = data.get('author', [])
        authors = ', '.join([f"{author.get('given', '')} {author.get('family', '')}".strip() for author in authors_list])
        journal = data.get('container-title', ['N/A'])[0]
        published = data.get('published-print', data.get('published-online', {}))
        year = published.get('date-parts', [[None]])[0][0]
        doi_url = data.get('URL', f"https://doi.org/{doi}")
        return {'title': title, 'authors': authors, 'journal': journal, 'year': year, 'url': doi_url}
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from CrossRef: {e}")
        return None

def add_paper_to_notion(paper_info, api_key, db_id):
    notion = Client(auth=api_key)
    try:
        new_page_properties = {
            'Name': {'title': [{'text': {'content': paper_info['title']}}]},
            'Authors': {'rich_text': [{'text': {'content': paper_info['authors']}}]},
            'Journal / Proc.': {'rich_text': [{'text': {'content': paper_info['journal']}}]},
            'year': {'number': paper_info['year']},
            'URL': {'url': paper_info['url']},
            'Status': {'select': {'name': 'Still'}}
        }
        notion.pages.create(parent={"database_id": db_id}, properties=new_page_properties)
        return f"Successfully added '{paper_info['title']}'"
    except Exception as e:
        return f"Error adding to Notion: {e}"

# --- 初回設定用GUIクラス (ポップアップ表示に修正) ---
class SetupWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("初回設定")
        self.root.geometry("450x200")
        
        frame = ttk.Frame(root, padding="10")
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Notion APIキーを入力してください:").pack(pady=5)
        self.api_key_entry = ttk.Entry(frame, width=50)
        self.api_key_entry.pack()

        ttk.Label(frame, text="Notion データベースIDを入力してください:").pack(pady=5)
        self.db_id_entry = ttk.Entry(frame, width=50)
        self.db_id_entry.pack()
        
        ttk.Button(frame, text="保存して開始", command=self.save_and_launch).pack(pady=20)

    def save_and_launch(self):
        api_key = self.api_key_entry.get().strip()
        db_id = self.db_id_entry.get().strip()

        if not api_key or not db_id:
            messagebox.showerror("入力エラー", "APIキーとデータベースIDの両方を入力してください。")
            return
        
        try:
            save_config(api_key, db_id)
            messagebox.showinfo("設定完了", "設定が保存されました。メイン画面に切り替わります。")
            self.transition_to_main_app(api_key, db_id)
        except Exception as e:
            messagebox.showerror("設定エラー", f"設定の保存中にエラーが発生しました。\n\n詳細: {e}")

    def transition_to_main_app(self, api_key, db_id):
        for widget in self.root.winfo_children():
            widget.destroy()
        PaperAdderApp(self.root, api_key, db_id)

# --- メインGUIアプリケーションクラス ---
class PaperAdderApp:
    def __init__(self, root, api_key, db_id):
        self.root = root
        self.api_key = api_key
        self.db_id = db_id
        
        self.root.title("Notion Paper Adder")
        self.root.geometry("420x320")
        self.selected_pdf_path = None
        
        pdf_frame = ttk.LabelFrame(root, text="PDFファイルから追加", padding=(10, 5))
        pdf_frame.pack(padx=10, pady=10, fill="x")
        self.select_button = ttk.Button(pdf_frame, text="PDFファイルを選択...", command=self.select_pdf_file)
        self.select_button.pack(pady=5)
        self.file_label = ttk.Label(pdf_frame, text="ファイルが選択されていません", wraplength=380)
        self.file_label.pack(pady=5)
        self.add_from_pdf_button = ttk.Button(pdf_frame, text="このPDFからNotionに追加", command=self.start_process_from_pdf, state=tk.DISABLED)
        self.add_from_pdf_button.pack(pady=5)
        
        doi_frame = ttk.LabelFrame(root, text="DOIを手入力で追加", padding=(10, 5))
        doi_frame.pack(padx=10, pady=5, fill="x")
        doi_label = ttk.Label(doi_frame, text="論文のDOIを入力:")
        doi_label.pack()
        self.manual_doi_entry = ttk.Entry(doi_frame, width=40)
        self.manual_doi_entry.pack(pady=5)
        self.add_from_doi_button = ttk.Button(doi_frame, text="このDOIでNotionに追加", command=self.start_process_from_doi)
        self.add_from_doi_button.pack(pady=5)

        self.status_label = ttk.Label(root, text="Status: Ready", wraplength=400, anchor="center")
        self.status_label.pack(pady=10, fill="x", expand=True)

    def select_pdf_file(self):
        filepath = filedialog.askopenfilename(filetypes=(("PDF files", "*.pdf"),))
        if filepath:
            self.selected_pdf_path = filepath
            filename = filepath.split('/')[-1]
            self.file_label.config(text=f"選択中: {filename}")
            self.add_from_pdf_button.config(state=tk.NORMAL)
            self.status_label.config(text="Status: PDFが選択されました。")

    def set_ui_for_processing(self, processing=True):
        state = tk.DISABLED if processing else tk.NORMAL
        self.select_button.config(state=state)
        self.add_from_pdf_button.config(state=state)
        self.add_from_doi_button.config(state=state)
        self.manual_doi_entry.config(state=state)

    def start_process_from_pdf(self):
        if not self.selected_pdf_path: return
        self.set_ui_for_processing(True)
        self.status_label.config(text="Status: PDFからDOIを抽出しています...")
        threading.Thread(target=self.run_pdf_workflow).start()

    def start_process_from_doi(self):
        doi = self.manual_doi_entry.get().strip()
        if not doi:
            self.status_label.config(text="Status: DOIを入力してください。")
            return
        self.set_ui_for_processing(True)
        threading.Thread(target=self.process_doi, args=(doi,)).start()

    def run_pdf_workflow(self):
        doi = extract_doi_from_pdf(self.selected_pdf_path)
        if not doi:
            self.root.after(0, self.update_status, "このPDFからDOIが見つかりませんでした。")
            return
        self.process_doi(doi)

    def process_doi(self, doi):
        self.root.after(0, self.status_label.config, {'text': f"Status: DOIをチェック中... ({doi[:20]}...)"})
        if check_if_paper_exists(doi, self.api_key, self.db_id):
            self.root.after(0, self.update_status, "この論文は既に追加されています。")
            return
            
        self.root.after(0, self.status_label.config, {'text': "Status: 論文情報を取得中..."})
        paper_data = get_paper_info_from_doi(doi)
        
        if paper_data:
            self.root.after(0, self.status_label.config, {'text': "Status: Notionに追加中..."})
            result_message = add_paper_to_notion(paper_data, self.api_key, self.db_id)
        else:
            result_message = "Status: 論文情報の取得に失敗しました。"
        
        self.root.after(0, self.update_status, result_message)

    def update_status(self, message):
        """処理完了後にポップアップを表示し、GUIをリセットする"""
        clean_message = message.replace("Status: ", "")

        if message.startswith("Successfully added"):
            messagebox.showinfo("成功", clean_message)
        elif "既に追加されています" in message or "見つかりませんでした" in message:
            messagebox.showwarning("警告", clean_message)
        else:
            messagebox.showerror("エラー", clean_message)

        # UIをリセット
        self.status_label.config(text="Status: Ready")
        self.set_ui_for_processing(False)
        self.file_label.config(text="ファイルが選択されていません")
        self.manual_doi_entry.delete(0, tk.END)
        self.selected_pdf_path = None
        self.add_from_pdf_button.config(state=tk.DISABLED)

# --- アプリケーション起動ロジック ---
if __name__ == "__main__":
    root = tk.Tk()
    config = load_config()

    if config:
        PaperAdderApp(root, config['api_key'], config['db_id'])
    else:
        SetupWindow(root)

    root.mainloop()

