# Console visual regression

The baseline represents the approved UI of the real Console routes. The legacy
`untitled/` prototype is migration reference only and is not started by this
harness.

Run the regression check:

```powershell
node .\visual-diff\run-visual-diff.mjs
```

Update the baseline only after reviewing an intentional UI change:

```powershell
node .\visual-diff\run-visual-diff.mjs --update-baseline
```

The check covers desktop and mobile, admin and user roles, login, protected
route fallback, retained management pages, detail pages, and representative
empty/error states. It fails when either the pixel-weighted overall similarity
or any individual scenario is below 98 percent.
