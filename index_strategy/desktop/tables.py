"""Scrollable native DataFrame-style views, bounded independently of disk history."""
from tkinter import ttk

import customtkinter as ctk


class DataTable(ctk.CTkFrame):
    def __init__(self, parent, columns, *, font_family, height=6, limit=400):
        super().__init__(parent, fg_color="white", corner_radius=0)
        self.limit = limit
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        scale = self._get_widget_scaling()
        style = ttk.Style(self)
        if style.theme_use() != "clam":
            style.theme_use("clam")
        style.configure("Delta1.Treeview", background="white", fieldbackground="white", foreground="#243D4B",
                        borderwidth=0, rowheight=round(25 * scale), font=(font_family, 10))
        style.configure("Delta1.Treeview.Heading", background="#EDF3F6", foreground="#425968",
                        font=(font_family, 10), relief="flat", padding=(5, 7))
        style.map("Delta1.Treeview", background=[("selected", "#D6EEEA")], foreground=[("selected", "#123F3D")])
        self.tree = ttk.Treeview(self, columns=[key for key, _, _ in columns], show="headings",
                                 height=height, style="Delta1.Treeview", selectmode="browse")
        for key, title, width in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=round(width * scale), minwidth=round(45 * scale), stretch=False, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.tag_configure("success", foreground="#087F78")
        self.tree.tag_configure("partial", foreground="#A5650C")
        self.tree.tag_configure("warning", foreground="#A5650C")
        self.tree.tag_configure("failed", foreground="#B94242")
        self.tree.tag_configure("alternate", background="#F7F9FB")

    def append(self, identifier, values, tag="", *, scroll=True):
        identifier = str(identifier)
        if not self.tree.exists(identifier):
            tags = (tag,) if tag else (("alternate",) if len(self.tree.get_children()) % 2 else ())
            self.tree.insert("", "end", iid=identifier, values=values, tags=tags)
        children = self.tree.get_children()
        if len(children) > self.limit:
            self.tree.delete(*children[:-self.limit])
        if scroll:
            self.tree.see(identifier)

    def clear(self):
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
