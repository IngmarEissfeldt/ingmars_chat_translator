import tkinter as tk
from tkinter import ttk, messagebox
import keyring


class ApiKeyDialog(tk.Toplevel):
    SERVICE = "MyAwesomeApp"
    USERNAME = "gemini_api_key"

    def __init__(self, parent):
        super().__init__(parent)

        self.title("Gemini API Key")
        self.geometry("450x180")
        self.resizable(False, False)

        self.result = None

        ttk.Label(
            self,
            text="Enter your Gemini API key:"
        ).pack(pady=(20, 5))

        self.entry = ttk.Entry(self, width=50, show="*")
        self.entry.pack(padx=20)

        ttk.Button(
            self,
            text="Save",
            command=self.save_key
        ).pack(pady=15)

        self.transient(parent)
        self.grab_set()

    def save_key(self):
        api_key = self.entry.get().strip()

        if not api_key:
            messagebox.showerror(
                "Error",
                "Please enter an API key.",
                parent=self
            )
            return

        # Store it in the OS credential store
        keyring.set_password(
            self.SERVICE,
            self.USERNAME,
            api_key
        )

        self.result = api_key
        self.destroy()