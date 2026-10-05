import os
import sys
import time
import json
import socket
import queue
import threading
import mimetypes
import webbrowser
import subprocess
import http.server
import socketserver
import urllib.request
import customtkinter as ctk

# Ensure terminal encoding compatibility on Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Paths & Settings
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(DIRECTORY, ".server.pid")
DEFAULT_PORT = 8080

# Configure MIME types
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/json', '.json')
mimetypes.add_type('application/geo+json', '.geojson')
mimetypes.add_type('text/csv', '.csv')

# Global thread-safe log queue
log_queue = queue.Queue()


class ModernHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom request handler with live GUI logging and CORS/no-cache headers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        # Local shutdown endpoint
        if self.path in ('/stop', '/shutdown', '/__stop__'):
            client_ip = self.client_address[0]
            if client_ip in ('127.0.0.1', 'localhost', '::1'):
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b"Server shutdown initiated.")
                log_queue.put(("[STOP]", "Shutdown command received via HTTP request."))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

        super().do_GET()

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()

    def log_message(self, format, *args):
        formatted = format % args
        status_code = ""
        parts = formatted.split()
        if len(parts) >= 2 and parts[1].isdigit():
            status_code = parts[1]

        timestamp = time.strftime("%H:%M:%S")
        log_queue.put((status_code or "HTTP", f"[{timestamp}] {formatted}"))


class ServerGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Appearance configuration
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("LIGTAS-AGAD • Virtual Server Controller")
        self.geometry("820x720")
        self.minsize(760, 640)

        # Server State Variables
        self.server_instance = None
        self.server_thread = None
        self.is_running = False
        self.active_port = DEFAULT_PORT
        self.start_time = None
        self.auto_scroll_enabled = True

        # Build UI Components
        self._create_header()
        self._create_status_card()
        self._create_controls_card()
        self._create_configuration_card()
        self._create_console_card()

        # Start background polling loops
        self._poll_logs()
        self._update_uptime_ticker()

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # Check if server is already running externally on launch
        self.after(300, self._check_initial_server_status)

    def _create_header(self):
        """Top branding header with theme toggle."""
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=24, pady=(18, 10))

        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(side="left")

        title_label = ctk.CTkLabel(
            title_box,
            text="LIGTAS-AGAD Virtual Server",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        )
        title_label.pack(anchor="w")

        subtitle_label = ctk.CTkLabel(
            title_box,
            text="Geospatial Early Warning System • Local Development Server",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=("#64748b", "#94a3b8")
        )
        subtitle_label.pack(anchor="w")

        # Theme toggle switch
        self.theme_switch = ctk.CTkSwitch(
            header_frame,
            text="Dark Mode",
            command=self._toggle_theme,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            onvalue="dark",
            offvalue="light"
        )
        self.theme_switch.select()
        self.theme_switch.pack(side="right", pady=5)

    def _create_status_card(self):
        """Hero card displaying current server status, live URL, and uptime."""
        self.status_card = ctk.CTkFrame(
            self,
            fg_color=("#f1f5f9", "#1e293b"),
            corner_radius=12,
            border_width=1,
            border_color=("#e2e8f0", "#334155")
        )
        self.status_card.pack(fill="x", padx=24, pady=8)

        # Card inner layout
        card_content = ctk.CTkFrame(self.status_card, fg_color="transparent")
        card_content.pack(fill="x", padx=20, pady=16)

        # Left Column: Status Badge & Live URL
        left_col = ctk.CTkFrame(card_content, fg_color="transparent")
        left_col.pack(side="left", fill="both", expand=True)

        badge_row = ctk.CTkFrame(left_col, fg_color="transparent")
        badge_row.pack(anchor="w", pady=(0, 6))

        self.status_badge = ctk.CTkLabel(
            badge_row,
            text="● OFFLINE",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=("#fee2e2", "#3f1d24"),
            text_color=("#dc2626", "#f87171"),
            corner_radius=12,
            padx=12,
            pady=4
        )
        self.status_badge.pack(side="left")

        self.uptime_label = ctk.CTkLabel(
            badge_row,
            text="Uptime: 00:00:00",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=("#64748b", "#94a3b8"),
            padx=12
        )
        self.uptime_label.pack(side="left")

        # URL text with clickable look
        self.url_label = ctk.CTkLabel(
            left_col,
            text="Server is not running",
            font=ctk.CTkFont(family="Consolas", size=15, weight="bold"),
            text_color=("#64748b", "#94a3b8")
        )
        self.url_label.pack(anchor="w", pady=(2, 0))

        # Root directory path display
        self.dir_label = ctk.CTkLabel(
            left_col,
            text=f"Serving: {DIRECTORY}",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=("#94a3b8", "#64748b")
        )
        self.dir_label.pack(anchor="w", pady=(4, 0))

        # Right Column: Quick URL Copy Button
        right_col = ctk.CTkFrame(card_content, fg_color="transparent")
        right_col.pack(side="right", padx=(10, 0))

        self.copy_btn = ctk.CTkButton(
            right_col,
            text="Copy Link",
            width=90,
            height=32,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=("#e2e8f0", "#334155"),
            hover_color=("#cbd5e1", "#475569"),
            text_color=("#334155", "#e2e8f0"),
            command=self._copy_link
        )
        self.copy_btn.pack(pady=4)

    def _create_controls_card(self):
        """Action button bar with Start, Stop, Open Browser, and Folder buttons."""
        controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        controls_frame.pack(fill="x", padx=24, pady=8)

        # Start Button (Vibrant Emerald / Teal)
        self.start_btn = ctk.CTkButton(
            controls_frame,
            text="▶  Start Server",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=44,
            fg_color="#0d9488",
            hover_color="#0f766e",
            text_color="#ffffff",
            corner_radius=10,
            command=self.start_server
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        # Stop Button (Coral Red)
        self.stop_btn = ctk.CTkButton(
            controls_frame,
            text="⏹  Stop Server",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=44,
            fg_color="#e11d48",
            hover_color="#be123c",
            text_color="#ffffff",
            corner_radius=10,
            state="disabled",
            command=self.stop_server
        )
        self.stop_btn.pack(side="left", fill="x", expand=True, padx=6)

        # Open in Browser Button
        self.browser_btn = ctk.CTkButton(
            controls_frame,
            text="🌐  Open Browser",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            height=44,
            fg_color=("#3b82f6", "#2563eb"),
            hover_color=("#2563eb", "#1d4ed8"),
            text_color="#ffffff",
            corner_radius=10,
            state="disabled",
            command=self.open_browser
        )
        self.browser_btn.pack(side="left", fill="x", expand=True, padx=6)

        # Open Directory Folder Button
        self.folder_btn = ctk.CTkButton(
            controls_frame,
            text="📂  Folder",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            height=44,
            width=100,
            fg_color=("#e2e8f0", "#334155"),
            hover_color=("#cbd5e1", "#475569"),
            text_color=("#334155", "#f1f5f9"),
            corner_radius=10,
            command=self.open_folder
        )
        self.folder_btn.pack(side="left", padx=(6, 0))

    def _create_configuration_card(self):
        """Configuration options: port number, auto-browser, no-cache."""
        config_frame = ctk.CTkFrame(
            self,
            fg_color=("#f8fafc", "#161f2e"),
            corner_radius=10,
            border_width=1,
            border_color=("#e2e8f0", "#243247")
        )
        config_frame.pack(fill="x", padx=24, pady=6)

        inner = ctk.CTkFrame(config_frame, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=10)

        # Port Setting
        port_label = ctk.CTkLabel(
            inner,
            text="Port:",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        )
        port_label.pack(side="left", padx=(0, 6))

        self.port_entry = ctk.CTkEntry(
            inner,
            width=80,
            height=30,
            font=ctk.CTkFont(family="Consolas", size=13)
        )
        self.port_entry.insert(0, str(DEFAULT_PORT))
        self.port_entry.pack(side="left", padx=(0, 24))

        # Auto Open Browser Checkbox
        self.auto_open_var = ctk.BooleanVar(value=True)
        self.auto_open_check = ctk.CTkCheckBox(
            inner,
            text="Auto-open browser on start",
            variable=self.auto_open_var,
            font=ctk.CTkFont(family="Segoe UI", size=12)
        )
        self.auto_open_check.pack(side="left", padx=10)

        # No-cache Headers Badge
        cache_badge = ctk.CTkLabel(
            inner,
            text="⚡ CORS & No-Cache Active",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=("#0d9488", "#2dd4bf")
        )
        cache_badge.pack(side="right", padx=(10, 0))

    def _create_console_card(self):
        """Live access and debug logs viewer."""
        console_container = ctk.CTkFrame(self, fg_color="transparent")
        console_container.pack(fill="both", expand=True, padx=24, pady=(6, 16))

        # Console Header
        console_header = ctk.CTkFrame(console_container, fg_color="transparent")
        console_header.pack(fill="x", pady=(0, 6))

        title = ctk.CTkLabel(
            console_header,
            text="Server Activity & Access Logs",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        )
        title.pack(side="left")

        # Clear logs button
        clear_btn = ctk.CTkButton(
            console_header,
            text="Clear Logs",
            width=70,
            height=26,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=("#e2e8f0", "#334155"),
            hover_color=("#cbd5e1", "#475569"),
            text_color=("#334155", "#e2e8f0"),
            command=self.clear_logs
        )
        clear_btn.pack(side="right")

        # Auto-scroll checkbox
        self.autoscroll_var = ctk.BooleanVar(value=True)
        autoscroll_check = ctk.CTkCheckBox(
            console_header,
            text="Auto-scroll",
            variable=self.autoscroll_var,
            font=ctk.CTkFont(family="Segoe UI", size=11)
        )
        autoscroll_check.pack(side="right", padx=12)

        # Log Textbox (Monospace terminal style)
        self.log_textbox = ctk.CTkTextbox(
            console_container,
            wrap="none",
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=("#ffffff", "#090d16"),
            border_width=1,
            border_color=("#e2e8f0", "#1e293b"),
            corner_radius=10
        )
        self.log_textbox.pack(fill="both", expand=True)

        self._log_info("LIGTAS-AGAD Virtual Server Controller initialized.")
        self._log_info(f"Target directory: {DIRECTORY}")

    def _log_info(self, message):
        """Append an informational message to the log queue."""
        timestamp = time.strftime("%H:%M:%S")
        log_queue.put(("INFO", f"[{timestamp}] [INFO] {message}"))

    def _poll_logs(self):
        """Pulls logs from thread-safe queue and inserts into the UI textbox."""
        try:
            while not log_queue.empty():
                tag, message = log_queue.get_nowait()
                self.log_textbox.configure(state="normal")
                self.log_textbox.insert("end", message + "\n")
                if self.autoscroll_var.get():
                    self.log_textbox.see("end")
                self.log_textbox.configure(state="disabled")
        except queue.Empty:
            pass

        self.after(100, self._poll_logs)

    def _update_uptime_ticker(self):
        """Updates the elapsed uptime counter while server is running."""
        if self.is_running and self.start_time:
            elapsed = int(time.time() - self.start_time)
            hours, rem = divmod(elapsed, 3600)
            minutes, seconds = divmod(rem, 60)
            self.uptime_label.configure(text=f"Uptime: {hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self.uptime_label.configure(text="Uptime: 00:00:00")

        self.after(1000, self._update_uptime_ticker)

    def _check_initial_server_status(self):
        """Checks on launch if a server is already running."""
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, 'r') as f:
                    data = json.load(f)
                port = data.get("port", DEFAULT_PORT)
                if self._is_port_listening(port):
                    self.active_port = port
                    self._set_ui_running_state(is_external=True)
                    self._log_info(f"Detected active server on port {port} (PID: {data.get('pid')})")
                    return
            except Exception:
                pass

        if self._is_port_listening(DEFAULT_PORT):
            self.active_port = DEFAULT_PORT
            self._set_ui_running_state(is_external=True)
            self._log_info(f"Port {DEFAULT_PORT} is currently active and serving requests.")

    def _is_port_listening(self, port):
        """Quick TCP socket test to see if a port is currently open."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            return s.connect_ex(('127.0.0.1', port)) == 0

    def start_server(self):
        """Starts the virtual server on the configured port."""
        if self.is_running:
            return

        port_str = self.port_entry.get().strip()
        if not port_str.isdigit():
            self._log_info("[ERROR] Invalid port. Please enter a valid number (e.g. 8080).")
            return

        port = int(port_str)
        if not (1 <= port <= 65535):
            self._log_info("[ERROR] Port must be between 1 and 65535.")
            return

        # Check if port is already occupied
        if self._is_port_listening(port):
            self._log_info(f"[WARN] Port {port} is already in use. Searching for an open port...")
            for alt_port in range(port + 1, port + 25):
                if not self._is_port_listening(alt_port):
                    port = alt_port
                    self.port_entry.delete(0, "end")
                    self.port_entry.insert(0, str(port))
                    self._log_info(f"[INFO] Using alternative port {port}.")
                    break
            else:
                self._log_info(f"[ERROR] Could not find an available port near {port_str}.")
                return

        self.active_port = port
        self.start_btn.configure(state="disabled")

        # Launch server in background thread
        threading.Thread(target=self._run_server_thread, args=(port,), daemon=True).start()

    def _run_server_thread(self, port):
        try:
            socketserver.TCPServer.allow_reuse_address = True
            self.server_instance = http.server.ThreadingHTTPServer(('127.0.0.1', port), ModernHTTPRequestHandler)

            # Record PID and port
            try:
                with open(PID_FILE, 'w') as f:
                    json.dump({"pid": os.getpid(), "port": port}, f)
            except Exception:
                pass

            self.start_time = time.time()
            self.is_running = True

            # Notify GUI of success
            self.after(0, self._set_ui_running_state)

            url = f"http://127.0.0.1:{port}/index.html"
            self._log_info(f"Server successfully started on {url}")

            # Auto-open browser if option is enabled
            if self.auto_open_var.get():
                self.after(800, self.open_browser)

            # Serve requests until stopped
            self.server_instance.serve_forever()

        except Exception as e:
            self._log_info(f"[ERROR] Server error: {e}")
            self.after(0, self._set_ui_stopped_state)
        finally:
            if self.server_instance:
                try:
                    self.server_instance.server_close()
                except Exception:
                    pass
            self.server_instance = None
            self.is_running = False
            self._cleanup_pid_file()
            self.after(0, self._set_ui_stopped_state)

    def stop_server(self):
        """Stops the virtual server (both in-process or external)."""
        self.stop_btn.configure(state="disabled")
        self.is_running = False
        self._log_info("Stopping virtual server...")

        def _do_stop():
            # 1. In-process server shutdown
            if self.server_instance:
                try:
                    self.server_instance.shutdown()
                    self.server_instance.server_close()
                except Exception:
                    pass
                self.server_instance = None

            # 2. Try HTTP shutdown command
            url = f"http://127.0.0.1:{self.active_port}/stop"
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'GUIStop'})
                urllib.request.urlopen(req, timeout=1.0)
            except Exception:
                pass

            # 3. Terminate external process if recorded in PID file
            if os.path.exists(PID_FILE):
                try:
                    with open(PID_FILE, 'r') as f:
                        data = json.load(f)
                    ext_pid = data.get("pid")
                    if ext_pid and ext_pid != os.getpid():
                        subprocess.run(["taskkill", "/F", "/PID", str(ext_pid)], capture_output=True)
                except Exception:
                    pass

            self._cleanup_pid_file()
            self.is_running = False
            self.after(0, self._set_ui_stopped_state)
            self._log_info("Server has been successfully stopped.")

        threading.Thread(target=_do_stop, daemon=True).start()

    def _set_ui_running_state(self, is_external=False):
        """Updates visual widgets when server is active."""
        self.is_running = True
        url = f"http://127.0.0.1:{self.active_port}/index.html"

        # Badge: Online Emerald
        badge_text = "● ONLINE (EXTERNAL)" if is_external else "● ONLINE"
        self.status_badge.configure(
            text=badge_text,
            fg_color=("#dcfce7", "#064e3b"),
            text_color=("#16a34a", "#34d399")
        )

        # URL
        self.url_label.configure(
            text=url,
            text_color=("#0d9488", "#2dd4bf")
        )

        # Buttons
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.browser_btn.configure(state="normal")
        self.port_entry.configure(state="disabled")

    def _set_ui_stopped_state(self):
        """Updates visual widgets when server is offline."""
        self.is_running = False
        self.start_time = None

        # Badge: Offline Red
        self.status_badge.configure(
            text="● OFFLINE",
            fg_color=("#fee2e2", "#3f1d24"),
            text_color=("#dc2626", "#f87171")
        )

        # URL
        self.url_label.configure(
            text="Server is not running",
            text_color=("#64748b", "#94a3b8")
        )

        # Buttons
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.browser_btn.configure(state="disabled")
        self.port_entry.configure(state="normal")

    def open_browser(self):
        """Opens active index.html URL in the default browser."""
        url = f"http://127.0.0.1:{self.active_port}/index.html"
        self._log_info(f"Opening browser at: {url}")
        webbrowser.open(url)

    def open_folder(self):
        """Opens Windows Explorer at the project root directory."""
        self._log_info(f"Opening project directory: {DIRECTORY}")
        try:
            if sys.platform == 'win32':
                os.startfile(DIRECTORY)
            else:
                subprocess.Popen(['xdg-open', DIRECTORY])
        except Exception as e:
            self._log_info(f"[ERROR] Could not open directory: {e}")

    def _copy_link(self):
        """Copies the URL to clipboard with visual feedback."""
        url = f"http://127.0.0.1:{self.active_port}/index.html"
        self.clipboard_clear()
        self.clipboard_append(url)
        self.update()

        # Temporary button feedback
        original_text = self.copy_btn.cget("text")
        self.copy_btn.configure(text="✓ Copied!")
        self.after(1400, lambda: self.copy_btn.configure(text=original_text))

    def clear_logs(self):
        """Clears the console log textbox."""
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def _toggle_theme(self):
        """Toggles between Dark Mode and Light Mode."""
        mode = self.theme_switch.get()
        ctk.set_appearance_mode(mode)
        if mode == "dark":
            self.theme_switch.configure(text="Dark Mode")
        else:
            self.theme_switch.configure(text="Light Mode")

    def _cleanup_pid_file(self):
        """Removes the PID file if it exists."""
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except Exception:
                pass

    def _on_window_close(self):
        """Safely stops server before exiting application."""
        if self.is_running and self.server_instance:
            try:
                self.server_instance.shutdown()
                self.server_instance.server_close()
            except Exception:
                pass
        self._cleanup_pid_file()
        self.destroy()


def main():
    app = ServerGUI()
    app.mainloop()


if __name__ == '__main__':
    main()
