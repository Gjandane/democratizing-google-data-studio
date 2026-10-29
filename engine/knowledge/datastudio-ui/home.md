---
type: UI Selector Set
title: Data Studio home
description: Home readiness for `dsengine login`, observed for task 14.2.
timestamp: 2026-10-29
selectors:
  studio_home: 'role=button[name="Reports and Data Apps"]'
  first_run_dialog: '[role="dialog"], [role="alertdialog"], mat-dialog-container'
---

The signed-in home (`/navigation/reporting`) shows a "Reports and Data Apps" asset
toggle beside Recent and no visible dialog. A fresh account first gets Data Studio's
first-run dialog (country, terms of service, Continue, then email preferences); it was
not observed live (the test account had accepted it), so `first_run_dialog` matches any
visible modal: the home is usable only with none showing. `login` never clicks it.

`<html lang>` carries the UI language (`en` here, with the selectors in English).
Chrome's per-site page zoom is `outerWidth / innerWidth` (window frame adds ~1%);
`devicePixelRatio` also includes the Windows display scale (2 here at 100% zoom).
