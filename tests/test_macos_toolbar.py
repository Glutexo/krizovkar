"""Testy nativního panelu nástrojů dostupného pouze na macOS."""

from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock


@unittest.skipUnless(sys.platform == "darwin", "vyžaduje AppKit")
class MacToolbarTest(unittest.TestCase):
    def test_toolbar_invokes_direct_and_menu_actions(self) -> None:
        from AppKit import NSApplication

        from krizovkar.macos_toolbar import _ToolbarDelegate

        NSApplication.sharedApplication()
        create_command = Mock()
        export_command = Mock()
        export_action = SimpleNamespace(
            identifier="blank-template",
            label="Šablonu k tisku (PDF)…",
            command=export_command,
        )
        create_item = SimpleNamespace(
            identifier="create-crossword",
            label="Vytvořit křížovku",
            tooltip="Vytvořit křížovku podle této šablony",
            image_name="doc.badge.plus",
            command=create_command,
            menu_actions=(),
        )
        export_item = SimpleNamespace(
            identifier="export",
            label="Exportovat",
            tooltip="Exportovat dokument do PDF",
            image_name="square.and.arrow.up",
            command=None,
            menu_actions=(export_action,),
        )
        delegate = _ToolbarDelegate.alloc().initWithItems_(
            (create_item, export_item)
        )
        assert delegate is not None

        create_toolbar_item = (
            delegate.toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(
                None,
                create_item.identifier,
                True,
            )
        )
        export_toolbar_item = (
            delegate.toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(
                None,
                export_item.identifier,
                True,
            )
        )
        assert create_toolbar_item is not None
        assert export_toolbar_item is not None
        menu_item = export_toolbar_item.menu().itemAtIndex_(0)

        application = NSApplication.sharedApplication()
        self.assertTrue(
            application.sendAction_to_from_(
                "performAction:",
                delegate,
                create_toolbar_item,
            )
        )
        self.assertTrue(
            application.sendAction_to_from_(
                "performAction:",
                delegate,
                menu_item,
            )
        )
        create_command.assert_called_once_with()
        export_command.assert_called_once_with()

        delegate.set_enabled(create_item.identifier, False)
        delegate.set_enabled(export_item.identifier, False)

        self.assertFalse(create_toolbar_item.isEnabled())
        self.assertFalse(export_toolbar_item.isEnabled())
        self.assertFalse(menu_item.isEnabled())
