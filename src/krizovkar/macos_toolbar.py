"""Nativní panel nástrojů dokumentového okna na macOS."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from typing import Protocol

import objc
from AppKit import (
    NSApp,
    NSImage,
    NSImageNameAddTemplate,
    NSImageNameShareTemplate,
    NSMenu,
    NSMenuItem,
    NSMenuToolbarItem,
    NSToolbar,
    NSToolbarDisplayModeIconAndLabel,
    NSToolbarItem,
    NSToolbarSizeModeRegular,
    NSWindowToolbarStyleUnified,
)
from Foundation import NSObject

_FALLBACK_IMAGES = {
    "doc.badge.plus": NSImageNameAddTemplate,
    "square.and.arrow.up": NSImageNameShareTemplate,
}


class ToolbarAction(Protocol):
    """Data jedné položky rozbalovací akce v panelu."""

    identifier: str
    label: str
    command: Callable[[], None]


class ToolbarItem(Protocol):
    """Data jedné přímé nebo rozbalovací položky panelu."""

    identifier: str
    label: str
    tooltip: str
    image_name: str
    command: Callable[[], None] | None
    menu_actions: Sequence[ToolbarAction]


class _ToolbarDelegate(NSObject):
    """Dodá AppKitu položky panelu a předá jejich akce do Pythonu."""

    def initWithItems_(
        self,
        items: Sequence[ToolbarItem],
    ) -> _ToolbarDelegate | None:
        self = objc.super(_ToolbarDelegate, self).init()
        if self is None:
            return None
        self._items = {item.identifier: item for item in items}
        self._commands = {
            action.identifier: action.command
            for item in items
            for action in item.menu_actions
        }
        self._commands.update(
            {
                item.identifier: item.command
                for item in items
                if item.command is not None
            }
        )
        self._enabled = {item.identifier: True for item in items}
        self._toolbar_items: dict[str, NSToolbarItem] = {}
        self._menu_items: dict[str, list[NSMenuItem]] = {}
        return self

    def toolbarDefaultItemIdentifiers_(self, _toolbar: NSToolbar) -> list[str]:
        return list(self._items)

    def toolbarAllowedItemIdentifiers_(self, _toolbar: NSToolbar) -> list[str]:
        return list(self._items)

    def toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(
        self,
        _toolbar: NSToolbar,
        item_identifier: str,
        _will_be_inserted: bool,
    ) -> NSToolbarItem | None:
        item = self._items.get(item_identifier)
        if item is None:
            return None

        if item.menu_actions:
            toolbar_item = self._menu_toolbar_item(item)
        else:
            toolbar_item = NSToolbarItem.alloc().initWithItemIdentifier_(
                item.identifier
            )
            toolbar_item.setTarget_(self)
            toolbar_item.setAction_("performAction:")

        toolbar_item.setLabel_(item.label)
        toolbar_item.setPaletteLabel_(item.label)
        toolbar_item.setToolTip_(item.tooltip)
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            item.image_name,
            item.label,
        )
        if image is None:
            fallback_name = _FALLBACK_IMAGES.get(
                item.image_name,
                NSImageNameShareTemplate,
            )
            image = NSImage.imageNamed_(fallback_name)
        toolbar_item.setImage_(image)
        toolbar_item.setEnabled_(self._enabled[item.identifier])
        self._toolbar_items[item.identifier] = toolbar_item
        return toolbar_item

    def _menu_toolbar_item(self, item: ToolbarItem) -> NSMenuToolbarItem:
        menu = NSMenu.alloc().initWithTitle_(item.label)
        menu.setAutoenablesItems_(False)
        menu_items: list[NSMenuItem] = []
        for action in item.menu_actions:
            menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                action.label,
                "performAction:",
                "",
            )
            menu_item.setTarget_(self)
            menu_item.setRepresentedObject_(action.identifier)
            menu_item.setEnabled_(self._enabled[item.identifier])
            menu.addItem_(menu_item)
            menu_items.append(menu_item)

        toolbar_item = NSMenuToolbarItem.alloc().initWithItemIdentifier_(
            item.identifier
        )
        toolbar_item.setMenu_(menu)
        self._menu_items[item.identifier] = menu_items
        return toolbar_item

    def performAction_(self, sender: NSMenuItem | NSToolbarItem) -> None:
        if isinstance(sender, NSToolbarItem):
            identifier = str(sender.itemIdentifier())
        else:
            identifier = str(sender.representedObject())
        command = self._commands.get(identifier)
        if command is not None:
            command()

    def set_enabled(self, identifier: str, enabled: bool) -> None:
        self._enabled[identifier] = enabled
        toolbar_item = self._toolbar_items.get(identifier)
        if toolbar_item is not None:
            toolbar_item.setEnabled_(enabled)
        for menu_item in self._menu_items.get(identifier, ()):
            menu_item.setEnabled_(enabled)


class MacWindowToolbar:
    """Připojí rozbalovací export přímo k nativnímu ``NSWindow``."""

    def __init__(
        self,
        window: tk.Toplevel,
        items: Sequence[ToolbarItem],
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

            delegate = _ToolbarDelegate.alloc().initWithItems_(items)
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

    def configure_action(self, identifier: str, *, state: str) -> None:
        """Sjednotí aktivní stav položky s dokumentem."""

        self._delegate.set_enabled(identifier, state != "disabled")
