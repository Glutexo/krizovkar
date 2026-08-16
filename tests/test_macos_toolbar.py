"""Testy nativního panelu nástrojů dostupného pouze na macOS."""

from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock


@unittest.skipUnless(sys.platform == "darwin", "vyžaduje AppKit")
class MacToolbarTest(unittest.TestCase):
    def test_export_menu_invokes_actions_and_follows_enabled_state(self) -> None:
        from AppKit import NSApplication

        from krizovkar.macos_toolbar import (
            _EXPORT_ITEM_IDENTIFIER,
            _ToolbarDelegate,
        )

        NSApplication.sharedApplication()
        command = Mock()
        action = SimpleNamespace(
            identifier="blank-template",
            label="Šablonu k tisku (PDF)…",
            command=command,
        )
        delegate = _ToolbarDelegate.alloc().initWithActions_((action,))
        assert delegate is not None

        toolbar_item = (
            delegate.toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(
                None,
                _EXPORT_ITEM_IDENTIFIER,
                True,
            )
        )
        assert toolbar_item is not None
        menu_item = toolbar_item.menu().itemAtIndex_(0)

        self.assertEqual("Exportovat", toolbar_item.label())
        self.assertEqual(action.label, menu_item.title())
        sent = NSApplication.sharedApplication().sendAction_to_from_(
            "performExport:",
            delegate,
            menu_item,
        )
        self.assertTrue(sent)
        command.assert_called_once_with()

        delegate.set_enabled(False)

        self.assertFalse(toolbar_item.isEnabled())
        self.assertFalse(menu_item.isEnabled())
