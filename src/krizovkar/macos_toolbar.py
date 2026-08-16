"""Nativní panel nástrojů dokumentového okna na macOS."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from typing import Protocol

import objc
from AppKit import (
    NSApp,
    NSImage,
    NSImageNameShareTemplate,
    NSMenu,
    NSMenuItem,
    NSMenuToolbarItem,
    NSToolbar,
    NSToolbarDisplayModeIconAndLabel,
    NSToolbarSizeModeRegular,
    NSWindowToolbarStyleUnified,
)
from Foundation import NSObject

_EXPORT_ITEM_IDENTIFIER = "cz.glutexo.krizovkar.toolbar.export"


class ToolbarAction(Protocol):
    """Data jedné položky rozbalovací akce v panelu."""

    identifier: str
    label: str
    command: Callable[[], None]


class _ToolbarDelegate(NSObject):
    """Dodá AppKitu položku exportu a předá její akce do Pythonu."""

    def initWithActions_(
        self,
        actions: Sequence[ToolbarAction],
    ) -> _ToolbarDelegate | None:
        self = objc.super(_ToolbarDelegate, self).init()
        if self is None:
            return None
        self._actions = {action.identifier: action for action in actions}
        self._enabled = True
        self._toolbar_item = None
        self._menu_items: list[NSMenuItem] = []
        return self

    def toolbarDefaultItemIdentifiers_(self, _toolbar: NSToolbar) -> list[str]:
        return [_EXPORT_ITEM_IDENTIFIER]

    def toolbarAllowedItemIdentifiers_(self, _toolbar: NSToolbar) -> list[str]:
        return [_EXPORT_ITEM_IDENTIFIER]

    def toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(
        self,
        _toolbar: NSToolbar,
        item_identifier: str,
        _will_be_inserted: bool,
    ) -> NSMenuToolbarItem | None:
        if item_identifier != _EXPORT_ITEM_IDENTIFIER:
            return None

        menu = NSMenu.alloc().initWithTitle_("Exportovat")
        menu.setAutoenablesItems_(False)
        self._menu_items = []
        for action in self._actions.values():
            menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                action.label,
                "performExport:",
                "",
            )
            menu_item.setTarget_(self)
            menu_item.setRepresentedObject_(action.identifier)
            menu_item.setEnabled_(self._enabled)
            menu.addItem_(menu_item)
            self._menu_items.append(menu_item)

        toolbar_item = NSMenuToolbarItem.alloc().initWithItemIdentifier_(
            item_identifier
        )
        toolbar_item.setLabel_("Exportovat")
        toolbar_item.setPaletteLabel_("Exportovat")
        toolbar_item.setToolTip_("Exportovat dokument do PDF")
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "square.and.arrow.up",
            "Exportovat",
        )
        if image is None:
            image = NSImage.imageNamed_(NSImageNameShareTemplate)
        toolbar_item.setImage_(image)
        toolbar_item.setMenu_(menu)
        toolbar_item.setEnabled_(self._enabled)
        self._toolbar_item = toolbar_item
        return toolbar_item

    def performExport_(self, sender: NSMenuItem) -> None:
        identifier = str(sender.representedObject())
        action = self._actions.get(identifier)
        if action is not None:
            action.command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if self._toolbar_item is not None:
            self._toolbar_item.setEnabled_(enabled)
        for menu_item in self._menu_items:
            menu_item.setEnabled_(enabled)


class MacWindowToolbar:
    """Připojí rozbalovací export přímo k nativnímu ``NSWindow``."""

    def __init__(
        self,
        window: tk.Toplevel,
        actions: Sequence[ToolbarAction],
    ) -> None:
        original_state = window.state()
        original_title = window.title()
        marker = f"KrizovkarToolbar-{id(window)}"
        window.withdraw()
        try:
            window.title(marker)
            window.update_idletasks()
            native_window = next(
                (
                    candidate
                    for candidate in NSApp.windows()
                    if candidate.title() == marker
                ),
                None,
            )
            if native_window is None:
                raise RuntimeError(
                    "Nativní okno pro panel nástrojů nebylo nalezeno."
                )

            delegate = _ToolbarDelegate.alloc().initWithActions_(actions)
            if delegate is None:
                raise RuntimeError("Panelu nástrojů nelze vytvořit obsluhu.")
            toolbar = NSToolbar.alloc().initWithIdentifier_(
                f"cz.glutexo.krizovkar.document.{id(window)}"
            )
            toolbar.setDelegate_(delegate)
            toolbar.setAllowsUserCustomization_(False)
            toolbar.setAutosavesConfiguration_(False)
            toolbar.setDisplayMode_(NSToolbarDisplayModeIconAndLabel)
            toolbar.setSizeMode_(NSToolbarSizeModeRegular)
            native_window.setToolbarStyle_(NSWindowToolbarStyleUnified)
            native_window.setToolbar_(toolbar)
            toolbar.setVisible_(True)

            self._native_window = native_window
            self._delegate = delegate
            self._toolbar = toolbar
        finally:
            window.title(original_title)
            if original_state != "withdrawn":
                window.deiconify()
                if original_state != "normal":
                    window.state(original_state)

    def configure(self, *, state: str) -> None:
        """Sjednotí aktivní stav s exportní nabídkou dokumentu."""

        self._delegate.set_enabled(state != "disabled")
