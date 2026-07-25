"""Mod editor shell: a sidebar of registered editor modules + a content area.

The shell knows nothing about concrete editors — it iterates `EditorRegistry.all()`,
instantiates each with a shared `ModContext`/`EditorServices`, and mounts the selected
one lazily. New editors appear here automatically once registered.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import ttk

from ...domain.mod import Mod, ModContext
from ...editors import EditorRegistry, EditorServices
from ..widgets.scrollable import ScrollableFrame

_NAV_GROUPS = {
    "general": "PROJECT",
    "countries": "WORLD SETUP", "map": "WORLD SETUP",
    "ideologies": "WORLD SETUP", "oob": "WORLD SETUP",
    "focuses": "CONTENT", "characters": "CONTENT", "traits": "CONTENT",
    "ideas": "CONTENT", "events": "CONTENT", "decisions": "CONTENT",
    "technologies": "CONTENT", "equipment": "CONTENT", "doctrines": "CONTENT",
    "interface": "SYSTEMS", "on_actions": "SYSTEMS",
    "dynamic_modifiers": "SYSTEMS", "scripted_gui": "SYSTEMS",
    "scripted_loc": "SYSTEMS",
}
_NAV_ORDER = ("PROJECT", "WORLD SETUP", "CONTENT", "SYSTEMS", "TOOLS")


class ModEditorScreen(ttk.Frame):
    def __init__(self, master, app, mod: Mod, progress=None):
        """`progress(done, total, label)` — optional loading-screen callback,
        called before each editor module is instantiated and before the first
        module's UI is built (the two slow phases of opening a mod)."""
        super().__init__(master, style="TFrame")
        self.app = app
        self.mod = mod
        self.context = ModContext(
            mod=mod,
            game_path=Path(app.settings.current.game_path),
            dependencies=app.repo.resolve_dependencies(mod),
        )
        self.services = EditorServices(
            t=app.t, theme=app.theme, settings=app.settings,
            cache=self.context.runtime.cache, tasks=self.context.runtime.tasks)

        classes = EditorRegistry.all()
        total = len(classes) + 1                 # +1 for building the first editor UI
        self._modules = []
        for i, cls in enumerate(classes):
            if progress is not None:
                progress(i, total, app.t(cls.name_key))
            self._modules.append(cls(self.context, self.services))
        self._built: dict[str, ttk.Widget] = {}
        self._buttons: dict[str, ttk.Button] = {}
        self._active: str | None = None
        if progress is not None:
            progress(total - 1, total, "")
        self._build()

    def _build(self) -> None:
        t = self.app.t
        header = ttk.Frame(self, style="TFrame")
        header.pack(fill="x", padx=24, pady=(14, 8))
        ttk.Button(header, text="‹ " + t("common.back"), command=self.app.show_mod_list).pack(side="left")
        ttk.Button(header, text="☰ " + t("editor.modules"),
                   command=self._toggle_sidebar).pack(side="left", padx=(8, 0))
        ttk.Button(header, text="📂 " + t("editor.open_folder"),
                   command=self._open_mod_folder).pack(side="right")
        self._task_status = ttk.Label(header, text="", style="Muted.TLabel")
        self._task_status.pack(side="right", padx=14)
        self.after(200, self._poll_tasks)

        self._body = ttk.Frame(self, style="TFrame")
        self._body.pack(fill="both", expand=True, padx=20, pady=(4, 16))
        self._body.columnconfigure(0, weight=0, minsize=236)
        self._body.columnconfigure(1, weight=1)
        self._body.rowconfigure(0, weight=1)

        self._sidebar = ttk.Frame(
            self._body, style="Sidebar.TFrame", padding=(10, 12))
        self._sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        ttk.Label(self._sidebar, text=self.mod.name, style="Heading.TLabel",
                  wraplength=205).pack(anchor="w", padx=8, pady=(0, 2))
        ttk.Label(self._sidebar, text=str(self.mod.path), style="CardMuted.TLabel",
                  wraplength=205).pack(anchor="w", padx=8, pady=(0, 10))
        # Scrolls when the module list outgrows the window height.
        scroll = ScrollableFrame(self._sidebar, bg=self.app.palette.surface,
                                 autohide=True, width=216)
        scroll.pack(fill="both", expand=True)
        scroll.body.configure(style="Sidebar.TFrame")
        last_group = None
        nav_modules = sorted(
            enumerate(self._modules),
            key=lambda item: (
                _NAV_ORDER.index(_NAV_GROUPS.get(item[1].id, "TOOLS")),
                item[0],
            ),
        )
        for _original_index, module in nav_modules:
            group = _NAV_GROUPS.get(module.id, "TOOLS")
            if group != last_group:
                ttk.Label(scroll.body, text=group, style="NavSection.TLabel").pack(
                    fill="x", padx=10, pady=(10 if last_group else 2, 3))
                last_group = group
            label = module.title + ("" if module.implemented else "  ·")
            btn = ttk.Button(scroll.body, text=label, style="Sidebar.TButton",
                             command=lambda m=module: self._select(m))
            btn.pack(fill="x", pady=2)
            self._buttons[module.id] = btn

        self._content = ttk.Frame(self._body, style="TFrame")
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.rowconfigure(1, weight=1)
        self._content.columnconfigure(0, weight=1)
        page_header = ttk.Frame(self._content, style="PageHeader.TFrame")
        page_header.grid(row=0, column=0, sticky="ew", pady=(2, 14))
        self._page_title = ttk.Label(page_header, text="", style="PageTitle.TLabel")
        self._page_title.pack(anchor="w")
        self._page_subtitle = ttk.Label(
            page_header, text="", style="PageSubtitle.TLabel", wraplength=900)
        self._page_subtitle.pack(anchor="w", pady=(2, 0))
        self._module_host = ttk.Frame(self._content, style="TFrame")
        self._module_host.grid(row=1, column=0, sticky="nsew")
        self._module_host.rowconfigure(0, weight=1)
        self._module_host.columnconfigure(0, weight=1)

        if self._modules:
            self._select(self._modules[0])

    def _open_mod_folder(self) -> None:
        """Open the mod's content root in the system file manager."""
        import os
        import subprocess
        import sys
        path = str(self.mod.path)
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError:
            pass

    def _toggle_sidebar(self) -> None:
        """Give canvas-heavy editors the whole window when desired."""
        if self._sidebar.winfo_ismapped():
            self._sidebar.grid_remove()
            self._body.columnconfigure(0, minsize=0)
        else:
            self._body.columnconfigure(0, minsize=236)
            self._sidebar.grid()

    def _poll_tasks(self) -> None:
        if not self.winfo_exists():
            return
        tasks = self.context.runtime.tasks.snapshot()
        running = [task for task in tasks if not task.future.done()]
        if running:
            average = round(sum(task.progress for task in running) /
                            len(running) * 100)
            self._task_status.configure(
                text=self.app.t("tasks.running", count=len(running),
                                progress=average))
        elif tasks:
            self._task_status.configure(text=self.app.t("tasks.finished"))
        else:
            self._task_status.configure(text="")
        self.after(200, self._poll_tasks)

    def _active_module(self):
        return next((m for m in self._modules if m.id == self._active), None)

    def on_leave(self) -> None:
        """Flush every opened module only when the mod editor itself closes."""
        for module in self._modules:
            if module.id not in self._built:
                continue
            hook = getattr(module, "on_leave", None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    pass
        self.context.runtime.tasks.shutdown(wait=False)

    def _select(self, module) -> None:
        if self._active == module.id:
            return
        # Built editors remain alive and retain their unsaved form state. Saving
        # and full validation can touch hundreds of files, so doing it on every
        # navigation click made tab switching feel like reopening the editor.
        for w in self._built.values():
            w.grid_remove()
        widget = self._built.get(module.id)
        if widget is None:
            widget = module.build(self._module_host)
            widget.grid(row=0, column=0, sticky="nsew")
            self._built[module.id] = widget
        else:
            widget.grid()
        self._active = module.id
        self._page_title.configure(text=module.title)
        self._page_subtitle.configure(text=module.description)
        for module_id, button in self._buttons.items():
            button.configure(style=("SidebarActive.TButton"
                                    if module_id == module.id
                                    else "Sidebar.TButton"))
