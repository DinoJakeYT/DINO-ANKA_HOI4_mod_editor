"""General editor: the default landing tab for a mod.

Shows the mod's descriptor metadata, a quick content summary (how many countries,
ideas, events, ... the mod defines) and the mod's **dependencies** — the sub-mods it
is layered on top of. Dependencies can be added from / removed against the list of
installed mods; changes are written straight back into the ``.mod`` descriptor.

Load order is game → dependencies (in listed order) → this mod, with later layers
overriding earlier ones, so an edited file in this mod always wins over the same file
in a dependency, which in turn wins over the base game.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ...services.mod_repository import ModRepository
from ...ui.widgets import ScrollableFrame
from ..base import EditorModule, EditorRegistry
from ..common.dialogs import MultiPickDialog


@EditorRegistry.register
class GeneralEditor(EditorModule):
    id = "general"
    name_key = "editors.general.name"
    desc_key = "editors.general.desc"
    order = 0

    def build(self, parent) -> ttk.Widget:
        outer = ttk.Frame(parent, style="TFrame")
        scroll = ScrollableFrame(outer, bg=self.palette.surface)
        scroll.pack(fill="both", expand=True)
        body = scroll.body
        body.configure(style="Card.TFrame", padding=20)
        body.columnconfigure(1, weight=1)
        t = self.t
        mod = self.context.mod
        r = 0

        ttk.Label(body, text=mod.name, style="CardTitle.TLabel").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(0, 2)); r += 1
        ttk.Label(body, text=t("general.subtitle"), style="CardMuted.TLabel").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(0, 14)); r += 1

        # --- descriptor metadata -------------------------------------------
        ttk.Label(body, text=t("general.section.mod"), style="Heading.TLabel").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(0, 6)); r += 1
        rows = [
            (t("general.path"), str(mod.path)),
            (t("general.version"), mod.version or "—"),
            (t("general.supported"), mod.supported_version or "—"),
            (t("general.source"), t("general.local") if mod.is_local
             else t("general.workshop")),
            (t("general.tags"), ", ".join(mod.tags) if mod.tags else "—"),
        ]
        for label, value in rows:
            ttk.Label(body, text=label, style="CardMuted.TLabel").grid(
                row=r, column=0, sticky="nw", pady=2)
            ttk.Label(body, text=value, style="Card.TLabel", wraplength=520,
                      justify="left").grid(row=r, column=1, sticky="w", padx=(12, 0),
                                           pady=2); r += 1

        # --- dependencies ---------------------------------------------------
        ttk.Separator(body).grid(row=r, column=0, columnspan=2, sticky="ew",
                                 pady=12); r += 1
        ttk.Label(body, text=t("general.section.dependencies"),
                  style="Heading.TLabel").grid(row=r, column=0, columnspan=2,
                                               sticky="w", pady=(0, 2)); r += 1
        ttk.Label(body, text=t("general.deps.hint"), style="CardMuted.TLabel",
                  wraplength=560, justify="left").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(0, 6)); r += 1
        self._deps_box = ttk.Frame(body, style="Card.TFrame")
        self._deps_box.grid(row=r, column=0, columnspan=2, sticky="ew"); r += 1
        self._deps_error = ttk.Label(body, text="", style="CardMuted.TLabel",
                                     wraplength=560, justify="left")
        self._deps_error.grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        self._render_deps()

        # --- content summary ------------------------------------------------
        ttk.Separator(body).grid(row=r, column=0, columnspan=2, sticky="ew",
                                 pady=12); r += 1
        ttk.Label(body, text=t("general.section.content"),
                  style="Heading.TLabel").grid(row=r, column=0, columnspan=2,
                                               sticky="w", pady=(0, 6)); r += 1
        self._summary = ttk.Label(body, text=t("general.counting"),
                                  style="CardMuted.TLabel", justify="left")
        self._summary.grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        ttk.Separator(body).grid(row=r, column=0, columnspan=2, sticky="ew",
                                 pady=12); r += 1
        ttk.Label(body, text=t("project.section"),
                  style="Heading.TLabel").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(0, 6)); r += 1
        actions = ttk.Frame(body, style="Card.TFrame")
        actions.grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        ttk.Button(actions, text=t("project.save_anka"),
                   command=self._save_anka).pack(side="left")
        ttk.Button(actions, text=t("project.export_hmb"),
                   command=self._export_hmb).pack(side="left", padx=(8, 0))
        self._project_status = ttk.Label(
            body, text="", style="CardMuted.TLabel")
        self._project_status.grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(6, 0)); r += 1
        # defer the (cheap but disk-touching) counts so the tab paints instantly
        outer.after(50, self._fill_summary)
        return outer

    # --- dependencies ------------------------------------------------------
    def _repo(self) -> ModRepository:
        return ModRepository(self.services.settings.current)

    def _render_deps(self) -> None:
        for w in self._deps_box.winfo_children():
            w.destroy()
        t = self.t
        deps = self.context.mod.dependencies
        installed = {m.name for m in self._repo().list_mods()}
        if not deps:
            ttk.Label(self._deps_box, text=t("general.deps.none"),
                      style="CardMuted.TLabel").pack(anchor="w", pady=(0, 4))
        for name in deps:
            row = ttk.Frame(self._deps_box, style="Card.TFrame")
            row.pack(fill="x", anchor="w", pady=1)
            ttk.Button(row, text="✕", width=2,
                       command=lambda n=name: self._remove_dep(n)).pack(side="left")
            ttk.Label(row, text=name, style="Card.TLabel").pack(side="left", padx=8)
            if name not in installed:
                ttk.Label(row, text=t("general.deps.missing"),
                          style="CardMuted.TLabel").pack(side="left", padx=4)
        ttk.Button(self._deps_box, text="＋ " + t("general.deps.add"),
                   command=self._add_deps).pack(anchor="w", pady=(6, 0))

    def _add_deps(self) -> None:
        mod = self.context.mod
        current = set(mod.dependencies)
        candidates = sorted({
            m.name for m in self._repo().list_mods()
            if m.name and m.id != mod.id and m.name != mod.name
            and m.name not in current
        })
        if not candidates:
            self._deps_error.configure(text=self.t("general.deps.no_candidates"))
            return
        self._deps_error.configure(text="")
        MultiPickDialog(self._deps_box, self, self.t("general.deps.pick"),
                        candidates, self._on_added)

    def _on_added(self, selected: list[str]) -> None:
        if selected:
            self._save_deps(self.context.mod.dependencies + list(selected))

    def _remove_dep(self, name: str) -> None:
        self._save_deps([d for d in self.context.mod.dependencies if d != name])

    def _save_deps(self, names: list[str]) -> None:
        # De-duplicate while preserving load order.
        ordered = list(dict.fromkeys(names))
        repo = self._repo()
        try:
            repo.save_dependencies(self.context.mod, ordered)
        except (OSError, FileNotFoundError):
            self._deps_error.configure(text=self.t("general.deps.save_failed"))
            return
        # Re-resolve so newly opened editor tabs layer the dependency content in.
        self.context.dependencies = repo.resolve_dependencies(self.context.mod)
        self._deps_error.configure(text=self.t("general.deps.reopen_note"))
        self._render_deps()

    def _fill_summary(self) -> None:
        def count_content() -> dict[str, int]:
            counts: dict[str, int] = {}
            try:
                from ...services.country_service import CountryService
                counts["countries"] = len(
                    CountryService(self.context).list_tags(include_vanilla=False))
            except Exception:
                pass
            try:
                from ...services.idea_service import IdeaService
                svc = IdeaService(self.context)
                counts["ideas"] = sum(len(v) for ref in svc.list_docs(False)
                                      for v in ref.categories.values())
            except Exception:
                pass
            try:
                from ...services.event_service import EventService
                counts["events"] = sum(
                    len(ref.events)
                    for ref in EventService(self.context).list_docs(False))
            except Exception:
                pass
            try:
                from ...services.decision_service import DecisionService
                counts["decisions"] = sum(
                    len(ids)
                    for ref in DecisionService(self.context).list_docs(False, "decisions")
                    for ids in ref.categories.values())
            except Exception:
                pass
            return counts

        def show(counts: dict[str, int]) -> None:
            lines = [self.t(f"general.count.{key}", count=value)
                     for key, value in counts.items()]
            self._summary.configure(
                text="\n".join(lines) or self.t("common.none"))

        self.services.tasks.submit_tk(
            self._summary, "Count mod content",
            lambda: self.services.cache.get(
                "general", "content-counts", count_content),
            show,
            lambda exc: self._summary.configure(
                text=f"{self.t('common.error')}: {exc}"),
        )

    def _save_anka(self) -> None:
        filename = filedialog.asksaveasfilename(
            parent=self._project_status, title=self.t("project.save_anka"),
            defaultextension=".anka",
            initialfile=f"{self.context.mod.id}.anka",
            filetypes=[("ANKA project", "*.anka")])
        if filename:
            self._run_project_task("Save ANKA project", Path(filename), "anka")

    def _export_hmb(self) -> None:
        filename = filedialog.asksaveasfilename(
            parent=self._project_status, title=self.t("project.export_hmb"),
            defaultextension=".hmb",
            initialfile=f"{self.context.mod.id}.hmb",
            filetypes=[("HOI4 Mod Builder project", "*.hmb")])
        if filename:
            self._run_project_task("Export HMB project", Path(filename), "hmb")

    def _run_project_task(self, name: str, destination: Path, kind: str) -> None:
        from ...services.project_exchange import export_hmb, save_anka
        operation = save_anka if kind == "anka" else export_hmb
        self._project_status.configure(text=self.t("project.working"))

        def done(_payload: dict) -> None:
            self._project_status.configure(
                text=self.t("project.saved", path=destination))

        def failed(exc: Exception) -> None:
            self._project_status.configure(text=self.t("project.failed"))
            messagebox.showerror(
                self.t("common.error"), str(exc), parent=self._project_status)

        self.services.tasks.submit_tk(
            self._project_status, name,
            lambda: operation(self.context, destination), done, failed)
