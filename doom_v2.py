import subprocess
import shutil
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog
from tkinter import ttk
import threading
import datetime
import os
import json
import zipfile
import tempfile
import urllib.request
import urllib.error
import platform
import ssl
import json as _json

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'doom_launcher_config.json')
ENGINES = ["gzdoom", "chocolate-doom", "prboom", "zdoom"]
CURRENT_LOG_FILE = None

# GitHub API endpoint for latest GZDoom release
GZDOOM_API_LATEST = "https://api.github.com/repos/gzdoom/gzdoom/releases/latest"

root = tk.Tk()


try:
    icon = tk.PhotoImage(file="doom_icon.ico")
except tk.TclError:
    print("Error: Image file not found or invalid format. Using default icon.")
    icon = None


def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        messagebox.showwarning("Config Warning", f"Could not load config: {e}")
    return {}


def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        messagebox.showwarning("Config Warning", f"Could not save config: {e}")


def download_gzdoom(config):
    """
    Fetch latest GZDoom release via GitHub API, or fallback to hardcoded version if API returns 404.
    """
    system = platform.system()
    dest_dir = os.path.join(os.path.dirname(__file__), 'engines', 'gzdoom')
    os.makedirs(dest_dir, exist_ok=True)

    data = None
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(GZDOOM_API_LATEST, headers={"User-Agent": "doom-launcher"})
        with urllib.request.urlopen(req, context=ctx) as resp:
            data = _json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            messagebox.showerror("Download Failed", f"Could not fetch GZDoom releases: HTTP {e.code}")
            return None
        # else 404: we'll fall back
    except Exception as e:
        messagebox.showerror("Download Failed", f"Could not fetch GZDoom releases: {e}")
        return None

    asset_url = None
    if data:
        # Select matching asset from API response
        for asset in data.get('assets', []):
            name = asset.get('name', '').lower()
            if system == 'Windows' and 'windows' in name and name.endswith('.zip'):
                asset_url = asset['browser_download_url']
            elif system == 'Darwin' and ('macos' in name or 'osx' in name):
                asset_url = asset['browser_download_url']
            elif system == 'Linux' and ('linux' in name and name.endswith('.tar.gz')):
                asset_url = asset['browser_download_url']
            if asset_url:
                break
    else:
        # Fallback to a known stable version
        version = '4.14.1'
        if system == 'Windows':
            asset_url = f'https://github.com/ZDoom/gzdoom/releases/download/g4.14.1/gzdoom-4-14-1-windows.zip'
        elif system == 'Darwin':
            asset_url = f'https://github.com/ZDoom/gzdoom/releases/download/g4.14.1/gzdoom-4-14-1-macos.zip'
        else:
            asset_url = f'https://github.com/ZDoom/gzdoom/releases/download/g4.14.1/gzdoom_4.14.1_amd64.deb'

    if not asset_url:
        messagebox.showerror("Download Failed", "No suitable GZDoom build found for your platform.")
        return None

    archive_path = os.path.join(dest_dir, os.path.basename(asset_url))
    try:
        urllib.request.urlretrieve(asset_url, archive_path)
    except urllib.error.HTTPError as e:
        messagebox.showerror("Download Failed", f"HTTP Error {e.code}: {e.reason}")
        return None
    except Exception as e:
        messagebox.showerror("Download Failed", f"Error downloading archive: {e}")
        return None

    # Extract archive
    try:
        if archive_path.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(dest_dir)
        elif archive_path.endswith('.tar.gz'):
            import tarfile
            with tarfile.open(archive_path, 'r:gz') as tf:
                tf.extractall(dest_dir)
        elif archive_path.endswith('.dmg'):
            messagebox.showinfo(
                "Manual Step Required",
                f"Please mount {archive_path} and copy GZDoom.app to {dest_dir}."
            )
            return None
    except Exception as e:
        messagebox.showerror("Extraction Failed", f"Could not extract GZDoom: {e}")
        return None

    # Locate the executable
    exe_path = None
    for root, _, files in os.walk(dest_dir):
        for file in files:
            low = file.lower()
            if 'gzdoom' in low and (low.endswith('.exe') or not os.path.splitext(low)[1]):
                exe_path = os.path.join(root, file)
                os.chmod(exe_path, 0o755)
                break
        if exe_path:
            break

    if not exe_path:
        messagebox.showerror("Error", "GZDoom executable not found after extraction.")
    return exe_path


def find_engine(engine_names, config=None):
    for name in engine_names:
        path = shutil.which(name)
        if path:
            return path
    if messagebox.askyesno("Engine Not Found", "No DOOM engine found. Download GZDoom now?"):
        return download_gzdoom(config or {})
    return None


def run_wad(wad_path, engine_choice=None, custom_engine_path=None, mod_paths=None,
            log_widget=None, status_label=None, launch_btn=None, config=None):
    global CURRENT_LOG_FILE
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    CURRENT_LOG_FILE = f"doom_log_{timestamp}.txt"

    def log(msg):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        line = f"[{ts}] {msg}"
        if log_widget:
            log_widget.insert(tk.END, line + "\n")
            log_widget.see(tk.END)
        try:
            with open(CURRENT_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(line + "\n")
        except Exception:
            pass

    if not os.path.isfile(wad_path):
        messagebox.showerror("Error", f"WAD file '{wad_path}' not found.")
        return

    mods = []
    if mod_paths:
        for p in mod_paths:
            if os.path.isfile(p):
                mods.append(p)
            else:
                messagebox.showerror("Error", f"Mod file '{p}' not found.")
                return

    # Determine engine
    if custom_engine_path:
        engine_path = custom_engine_path
    elif engine_choice and engine_choice != 'Auto':
        engine_path = shutil.which(engine_choice)
        if not engine_path:
            messagebox.showerror("Error", f"Engine '{engine_choice}' not found on PATH.")
            return
    else:
        engine_path = find_engine(ENGINES, config)
        if not engine_path:
            return

    cmd = [engine_path, '-iwad', wad_path] + sum([['-file', m] for m in mods], [])
    log("Launching: " + ' '.join(cmd))

    if status_label:
        status_label.config(text="Launching...")
    if launch_btn:
        launch_btn.config(state=tk.DISABLED)

    def launch():
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                log(line.strip())
            proc.wait()
            log("Process finished.")
        except Exception as e:
            log(f"Error: {e}")
            messagebox.showerror("Launch Failed", f"Failed to launch engine: {e}")
        finally:
            if status_label:
                status_label.after(0, lambda: status_label.config(text="Ready"))
            if launch_btn:
                launch_btn.after(0, lambda: launch_btn.config(state=tk.NORMAL))

    threading.Thread(target=launch, daemon=True).start()


def browse_file(entry_var, config_key, filetypes, title, config):
    initial = config.get(config_key, os.getcwd())
    path = filedialog.askopenfilename(title=title, filetypes=filetypes, initialdir=initial)
    if path:
        entry_var.set(path)
        config[config_key] = os.path.dirname(path)
        save_config(config)


def add_mods(listbox, config):
    initial = config.get('last_mod_dir', os.getcwd())
    paths = filedialog.askopenfilenames(
        title="Select Mod Files",
        filetypes=[("Mods", "*.wad;*.pk3;*.zip"), ("All", "*.*")],
        initialdir=initial
    )
    if paths:
        config['last_mod_dir'] = os.path.dirname(paths[0])
        save_config(config)
        for p in paths:
            if p not in listbox.get(0, tk.END):
                listbox.insert(tk.END, p)


def remove_selected(listbox):
    for idx in reversed(list(listbox.curselection())):
        listbox.delete(idx)


def export_mods(listbox, config, status_label=None):
    mods = list(listbox.get(0, tk.END))
    if not mods:
        messagebox.showinfo("Info", "No mods to export.")
        return
    initial = config.get('last_export_dir', os.getcwd())
    out_path = filedialog.asksaveasfilename(
        title="Export Combined Mod", defaultextension='.pk3',
        filetypes=[("PK3", "*.pk3"), ("WAD", "*.wad")], initialdir=initial
    )
    if not out_path:
        return
    config['last_export_dir'] = os.path.dirname(out_path)
    save_config(config)

    if status_label:
        status_label.config(text="Exporting mods...")

    try:
        with tempfile.TemporaryDirectory() as tempdir:
            for p in mods:
                ext = os.path.splitext(p)[1].lower()
                if ext in ['.zip', '.pk3']:
                    with zipfile.ZipFile(p, 'r') as zf:
                        zf.extractall(tempdir)
                else:
                    shutil.copy(p, os.path.join(tempdir, os.path.basename(p)))
            with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(tempdir):
                    for file in files:
                        full = os.path.join(root, file)
                        arc = os.path.relpath(full, tempdir)
                        zf.write(full, arc)
        messagebox.showinfo("Success", f"Combined mod exported to {out_path}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to export combined mod: {e}")
    finally:
        if status_label:
            status_label.config(text="Ready")


def open_log():
    if CURRENT_LOG_FILE and os.path.isfile(CURRENT_LOG_FILE):
        try:
            if sys.platform == 'win32':
                os.startfile(CURRENT_LOG_FILE)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', CURRENT_LOG_FILE])
            else:
                subprocess.Popen(['xdg-open', CURRENT_LOG_FILE])
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open log file: {e}")
    else:
        messagebox.showinfo("Info", "No log file available yet.")


def clear_log_widget(log_widget):
    log_widget.delete('1.0', tk.END)


def create_gui():
    config = load_config()
    presets = config.get('presets', {})

    root = tk.Tk()
    root.title("Kit Cat DOOM Player")
    root.resizable(False, False)
    root.report_callback_exception = lambda exc, val, tb: messagebox.showerror("Error", str(val))

    preset_var = tk.StringVar()
    wad_var = tk.StringVar()
    engine_var = tk.StringVar(value='Auto')
    custom_var = tk.StringVar()

    status_bar = ttk.Label(root, text="Ready", anchor='w')
    status_bar.grid(row=7, column=0, columnspan=4, sticky='we', padx=5, pady=(0,5))

    def save_current_preset():
        name = simpledialog.askstring("Preset Name", "Enter a name for this preset:", parent=root)
        if not name: return
        presets[name] = {
            'wad': wad_var.get(), 'engine': engine_var.get(),
            'custom': custom_var.get(), 'mods': list(mod_listbox.get(0, tk.END))
        }
        config['presets'] = presets; save_config(config)
        preset_cb['values'] = list(presets.keys()); preset_var.set(name)
        status_bar.config(text=f"Preset '{name}' saved.")

    def delete_current_preset():
        name = preset_var.get()
        if not name or name not in presets: return
        if messagebox.askyesno("Delete Preset", f"Delete preset '{name}'?"):
            presets.pop(name); config['presets'] = presets; save_config(config)
            preset_cb['values'] = list(presets.keys()); preset_var.set('')
            wad_var.set(''); engine_var.set('Auto'); custom_var.set(''); mod_listbox.delete(0, tk.END)
            status_bar.config(text=f"Preset '{name}' deleted.")

    def load_preset():
        name = preset_var.get()
        if not name or name not in presets: return
        data = presets[name]
        wad_var.set(data.get('wad','')); engine_var.set(data.get('engine','Auto'))
        custom_var.set(data.get('custom',''))
        mod_listbox.delete(0, tk.END)
        for m in data.get('mods', []): mod_listbox.insert(tk.END, m)
        status_bar.config(text=f"Preset '{name}' loaded.")

    def download_freedoom():
        status_bar.config(text="Downloading FreeDoom IWAD...")
        url = "https://github.com/freedoom/freedoom/releases/download/v0.13.0/freedoom-0.13.0.zip"
        try:
            dest = config.get('freedoom_dir', os.path.join(os.path.dirname(__file__), 'iwads'))
            os.makedirs(dest, exist_ok=True)
            zip_path = os.path.join(dest, 'freedoom-0.13.0.zip')
            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for name in zf.namelist():
                    if name.lower().endswith('freedoom2.wad'):
                        zf.extract(name, dest)
                        freedoom2 = os.path.join(dest, name)
                        break
                else:
                    messagebox.showerror("Error", "freedoom2.wad not found in archive.")
                    status_bar.config(text="Ready")
                    return
            wad_var.set(freedoom2)
            config['last_wad_dir'] = dest; save_config(config)
            status_bar.config(text="FreeDoom IWAD ready.")
        except Exception as e:
            messagebox.showerror("Download Failed", f"Failed to download FreeDoom: {e}")
            status_bar.config(text="Ready")

    # Layout
    tk.Label(root, text="Preset:").grid(row=0, column=0, padx=5, pady=5, sticky='e')
    preset_cb = ttk.Combobox(root, textvariable=preset_var, values=list(presets.keys()), state='readonly', width=40)
    preset_cb.grid(row=0, column=1, pady=5)
    preset_cb.bind('<<ComboboxSelected>>', lambda e: load_preset())
    tk.Button(root, text="Save (Ctrl+S)", command=save_current_preset).grid(row=0, column=2, padx=5)
    tk.Button(root, text="Delete (Ctrl+D)", command=delete_current_preset).grid(row=0, column=3, padx=5)

    tk.Label(root, text="WAD File:").grid(row=1, column=0, padx=5, pady=5, sticky='e')
    tk.Entry(root, textvariable=wad_var, width=50).grid(row=1, column=1)
    tk.Button(root, text="Browse...", command=lambda: browse_file(
        wad_var, 'last_wad_dir', [("WADs","*.wad;*.iwad"),("All","*.*")],
        "Select WAD file", config)).grid(row=1, column=2)
    tk.Button(root, text="Get FreeDoom", command=download_freedoom).grid(row=1, column=3)

    tk.Label(root, text="Engine:").grid(row=2, column=0, padx=5, pady=5, sticky='e')
    tk.OptionMenu(root, engine_var, *(['Auto'] + ENGINES)).grid(row=2, column=1, sticky='w')

    tk.Label(root, text="Custom Engine:").grid(row=3, column=0, padx=5, pady=5, sticky='e')
    tk.Entry(root, textvariable=custom_var, width=50).grid(row=3, column=1)
    tk.Button(root, text="Browse...", command=lambda: browse_file(
        custom_var, 'last_engine_dir',
        [("Exec","*.exe" if sys.platform=='win32' else "*"),("All","*.*")],
        "Select engine executable", config)).grid(row=3, column=2)

    tk.Label(root, text="Mod Files:").grid(row=4, column=0, padx=5, pady=5, sticky='ne')
    mod_listbox = tk.Listbox(root, selectmode=tk.MULTIPLE, width=50, height=4)
    mod_listbox.grid(row=4, column=1, pady=5)
    mod_btn_frame = tk.Frame(root)
    mod_btn_frame.grid(row=4, column=2, padx=5)
    tk.Button(mod_btn_frame, text="Add Mods...", command=lambda: add_mods(mod_listbox, config)).pack(fill='x', pady=2)
    tk.Button(mod_btn_frame, text="Remove...", command=lambda: remove_selected(mod_listbox)).pack(fill='x', pady=2)
    tk.Button(mod_btn_frame, text="Export...", command=lambda: export_mods(mod_listbox, config, status_bar)).pack(fill='x', pady=2)

    log_widget = scrolledtext.ScrolledText(root, width=80, height=12, state='normal')
    log_widget.grid(row=5, column=0, columnspan=4, padx=5, pady=5)

    btn_frame = tk.Frame(root)
    btn_frame.grid(row=6, column=0, columnspan=4, pady=5)
    launch_btn = tk.Button(btn_frame, text="Launch (Ctrl+Enter)", width=20,
                           command=lambda: run_wad(
                               wad_var.get(), engine_var.get(), custom_var.get() or None,
                               list(mod_listbox.get(0, tk.END)) or None,
                               log_widget, status_bar, launch_btn, config))
    launch_btn.pack(side='left', padx=5)
    tk.Button(btn_frame, text="Clear Log", width=10, command=lambda: clear_log_widget(log_widget)).pack(side='left', padx=5)
    tk.Button(btn_frame, text="Open Log", width=10, command=open_log).pack(side='left', padx=5)

    root.bind('<Control-s>', lambda e: save_current_preset())
    root.bind('<Control-d>', lambda e: delete_current_preset())
    root.bind('<Control-Return>', lambda e: launch_btn.invoke())

    root.mainloop()


if __name__ == '__main__':
    root.iconphoto(True, icon)
    create_gui()
