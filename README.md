# Affidian rates feed

The automated rates box for the Community Wall and vestibule screens.

Every morning, GitHub reads https://www.affidiancu.org/resources/tools/rates, checks the numbers, and updates `docs/rates.json`. The rates box page (`docs/index.html`) reads that file and shows one category at a time.

## What's in here

| File | What it does |
|---|---|
| `scraper/fetch_rates.py` | Reads the rates page, sorts rows into categories, checks them, writes `docs/rates.json` |
| `scraper/categories.json` | Which rows go in which category. **This is the file you'll edit most.** |
| `.github/workflows/update-rates.yml` | Runs the scraper every day at 10:00 UTC, plus a "Run workflow" button |
| `docs/index.html` | The rates box Intuiface shows |
| `docs/rates.json` | The rates. Starts as sample data until the first run |
| `docs/sw.js` | Keeps the last copy for when the player has no internet |

## Category URLs

`https://YOUR-SITE/index.html#savings`, then swap the ending for:
`#checking`, `#money-market`, `#certificates`, `#credit-cards`, `#personal-loans`, `#home-loans`, `#vehicle-loans`

Optional settings go before the `#`:
- `?footer=0` hides the note and effective date under the box
- `?return=0` hides the Return button
- Both: `index.html?footer=0&return=0#savings`

## If a daily run fails

GitHub emails the account owner. The screens keep showing the last good rates. Open the failed run on the **Actions** tab. The log lists every table it found on the page and what went wrong. Usually the fix is a small change to `categories.json`.

## Updating rates the same day

**Actions** tab, then **Update rates**, then **Run workflow**. The screens pick up the new rates within about 30 minutes, or right away when the page is reopened.
