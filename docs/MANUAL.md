# ☣️ BLACKSWARM // Complete User Manual

**GlitchByte Phantom Labs · v0.5.7 · Rainbow Skull Swarm Edition**

BLACKSWARM is a **terminal-first, public-index research tool** for gathering and organizing links. It offers multi-source discovery, heuristic relevance ranking, deduplication, colorful result maps, bookmarks, collections, tags, and explicitly requested local backup snapshots.

> **Important:** “Dork-style” describes search-query research, **not** direct Google/Bing scraping, intrusion, vulnerability exploitation, or private-network scanning. Each public source determines which query operators it supports. An indexed result does not establish that a site is safe, truthful, or currently online.

## Start here

Requires **Python 3** and the Python standard library. No separate Python packages, desktop integration, or system customization are required.

From the extracted project folder:

```bash
bash RUN-BLACKSWARM.sh --color always
```

The application opens the rainbow **SWARM COMMAND DECK**, where you select menu numbers and press Enter. BLACKSWARM does **not** automatically open a browser.

Run offline checks (tests do not require real search results):

```bash
python3 -m unittest discover -s tests -q
```

For the shorter introductory help, see [START-HERE.txt](START-HERE.txt) and [EXAMPLE-DESK.txt](EXAMPLE-DESK.txt).

## 🌈 Main menu: all 14 features

| Menu | Name | What it does |
|---|---|---|
| **1** | **LIVE PUBLIC-INDEX SEARCH** | Queries selected public research indexes, prints live progress/results in the terminal, deduplicates URLs, scores relevance, and saves a numbered session. |
| **2** | **OFFLINE DEMO** | Generates seven illustrative example URLs for learning the interface; **not live research**. |
| **3** | **SAVED SESSION HISTORY** | Lists actual saved searches with their **Session IDs**. |
| **4** | **SHOW ALL LINKS FROM A SESSION** | Prints selected, saved URLs, titles, sources, and relevance information from a chosen session. |
| **5** | **EXPORT SESSION** | Saves selected results as **CSV, JSON, or HTML**, or candidate records in **raw CSV/JSON**. Exports only when requested. |
| **6** | **OPTIONAL DASHBOARD** | Starts a local dashboard and prints its localhost URL. **Does not automatically open a browser**. |
| **7** | **REVIEW ALL EXCLUDED CANDIDATES** | Shows links collected but not selected for the saved result set, useful for reviewing what the relevance filter left out. |
| **8** | **EXAMPLE DESK** | Explains sessions, IDs, searches, and exports with clearly labeled sample data. |
| **9** | **SWARM CONSTELLATION** | Read-only rainbow charts of saved providers, domains, topic terms, and source overlap. |
| **10** | **SESSION DELTA** | Compares two saved research sessions: URLs only in the older set, only in the newer set, and shared by both. |
| **11** | **CONSTELLATION NAVIGATOR** | Browses saved results by source, topic, domain, relevance, or keyword. Can star a displayed link. |
| **12** | **BOOKMARKED INTEL** | Maintains an independent favorite-link shelf, private notes, searching, and CSV/JSON exports. |
| **13** | **INTEL COLLECTIONS** | Organizes starred links into folders; includes Collection Radar, Collection Pulse, and Swarm Tags. |
| **14** | **VAULT GUARD** | Previews BLACKSWARM databases, makes a separate private backup after confirmation, and verifies a saved backup. |
| **0** | **QUIT** | Exits BLACKSWARM. |

### 1 · Live public-index search

Select **[1]**, enter a research phrase, and choose your sources:

- **Wikipedia:** public encyclopedia search results.
- **Crossref:** scholarly publication and DOI metadata.
- **Open Library:** public catalog records.
- **Internet Archive:** indexed catalog and archive metadata.
- **Europe PMC:** biomedical and life-sciences publication records.
- **GDELT:** an additional public news-data source; may time out or fail independently.
- **SearXNG:** optional public **HTTPS** instance that you provide. Availability and operator support depend on that instance.

Press **Enter** at the sources prompt for the five default indexes: Wikipedia, Crossref, Open Library, Internet Archive, and Europe PMC. Other sources are opt-in. Available result limits are **50, 100, 250, 500, or 1,000** unique URLs; actual counts depend on provider results and deduplication. Choose **focused** (prioritize stronger heuristic matches) or **broad** (keep a wider ranked selection).

BLACKSWARM prints provider progress and the saved link results in the terminal, along with a new **Session ID**. Search totals, relevance labels, and source coverage are heuristics, **not proof of completeness or accuracy**. Respect provider policies and reasonable request volume.

### 2 · Offline demo

Select **[2]** to see **seven illustrative URLs**. These are educational examples, not evidence of a live search. The demo can produce a session in your local research vault.

### 3–5 · Session history, details, and exports

**[3]** shows your actual Session IDs. A **Session ID** identifies one stored search, not a bookmark or collection.

**[4]** asks for that Session ID and prints its saved links.

**[5]** asks for the Session ID and export format. The accepted format names are `csv`, `json`, `html`, `rawcsv`, and `rawjson`. The **raw** choices describe the collected candidate records, including those excluded from the final saved selection. Files are written to a local exports folder and are not opened automatically. Exported files may contain sensitive personal research choices; review them before sharing.

### 6 · Optional local dashboard

**[6]** starts a localhost dashboard and prints the URL so **you** decide whether to open it. The normal menu never automatically opens the browser. You can also start it directly with `--dashboard`; `--open-dashboard` explicitly requests browser opening.

### 7 · Excluded-candidate review

**[7]** opens records collected during a saved session that were **not chosen** for the final saved set. Use it to evaluate filtering and missed relevant items. This views stored data only.

### 8 · Example Desk

**[8]** explains the distinction between actual session numbers and illustrative sample sessions. At supported Session ID prompts, `?` displays help, and Enter cancels.

### 9 · Swarm Constellation

**[9]** creates **read-only terminal charts** from one saved session: distribution by provider and domain, frequently occurring words in titles, and URLs appearing in multiple sources. It makes no new web requests.

### 10 · Session Delta

**[10]** compares an **older** and **newer** saved Session ID. It reports URLs unique to either snapshot and shared URLs. **It does not prove that a public webpage was created, deleted, or changed** between searches.

### 11 · Constellation Navigator

**[11]** opens a saved session and lets you drill down by:

1. **Sources:** links grouped by contributing public index.
2. **Topic Stars:** keywords extracted from saved titles.
3. **Domain Nebula:** links grouped by hostname.
4. **Relevance:** HIGH, POSSIBLE, or LOW heuristic ranking.
5. **Quick Find:** search saved titles, URLs, and snippets.

Inside a result list use `n` (next page), `p` (previous), a **displayed result number** (details), or `b` (back). To favorite a visible link, type **`f`**, press Enter, and then enter its displayed number. Shortcut: **`f 1`** stars displayed item 1. You can add a note or press Enter to skip it. **Type the letter f; do not press the F1 function key.**

### 12 · Bookmarked Intel

Saved favorites have their own **Bookmark IDs** distinct from Session IDs. The shelf stores copied result metadata and optional notes in an independent local database.

| Menu | Bookmark control |
|---|---|
| **1** | View favorites and select a Bookmark ID to see its details |
| **2** | Star a link from a saved session |
| **3** | Edit an existing favorite note |
| **4** | Remove one favorite after typing the required confirmation |
| **5** | Export favorites as CSV or JSON |
| **6** | Quick-find existing favorite titles, URLs, and notes |
| **0** | Return to the command deck |

In the favorites viewer you can also type `e` and select a Bookmark ID to edit its note. Removing a favorite does **not** delete the original research-session link.

See [BOOKMARKS-GUIDE.txt](BOOKMARKS-GUIDE.txt) and [STAR-CONTROL-QUICKSTART.txt](STAR-CONTROL-QUICKSTART.txt).

### 13 · Intel Collections

Collections are **named folders of starred links**, independent of the original research vault and favorites database.

| Menu | Collection control |
|---|---|
| **1** | View collections and their saved links |
| **2** | Create a collection with optional description |
| **3** | Add an existing starred bookmark by **Bookmark ID** |
| **4** | Rename a collection or edit its description |
| **5** | Unlink an item **from that collection only**, after confirming |
| **6** | Export one collection as CSV or JSON |
| **7** | **Collection Radar:** search across locally saved collection titles, notes, URLs, sources, and folders; optionally filter to one Collection ID |
| **8** | **Collection Pulse:** rainbow chart of folder sizes, unique URLs, and cross-collection copies |
| **9** | **Swarm Tags:** open the label manager |
| **0** | Return to command deck |

#### Swarm Tags submenu: [13] → [9]

| Menu | Tag control |
|---|---|
| **1** | View currently tagged links in collections |
| **2** | Pick a Collection ID and its displayed Item ID; attach a custom tag |
| **3** | Remove a tag after typing the required confirmation |
| **4** | Find saved links by tag text |
| **5** | **Tag Nebula:** rainbow label-frequency chart |
| **0** | Return to Collections |

Tags apply to saved URLs across your collections. A tag label must contain **2–36 characters**. A collection's **Item ID** is different from the **Bookmark ID** used to add that link.

Example: create collection **Cybersecurity Reads** using [13] → [2]; add bookmark 1 using [3]; use [7] to find your saved research; enter [9] → [2] to add a label, then [9] → [5] to see the Tag Nebula.

See [INTEL-COLLECTIONS-GUIDE.txt](INTEL-COLLECTIONS-GUIDE.txt), [COLLECTION-RADAR-GUIDE.txt](COLLECTION-RADAR-GUIDE.txt), and [SWARM-TAGS-GUIDE.txt](SWARM-TAGS-GUIDE.txt).

### 14 · Vault Guard

Vault Guard makes **local snapshots of BLACKSWARM's own SQLite databases**. It is **not an external account recovery service**.

| Menu | Vault Guard control |
|---|---|
| **1** | Read-only preview: existing research, bookmarks, collections, and tags databases |
| **2** | Type **BACKUP** to create a new private ZIP containing consistent snapshots, an internal manifest, and SHA-256 verification |
| **3** | Verify an existing ZIP's checksums and database integrity; no restore or overwrite |
| **0** | Return to command deck |

**Backup ZIPs are not encrypted.** Do not commit them to public GitHub repositories or share them casually. Vault Guard intentionally has **no restore button**. It does not modify the live databases during backup creation.

See [VAULT-GUARD-GUIDE.txt](VAULT-GUARD-GUIDE.txt).

## 🧭 Useful command-line options

Launch these from the project folder by adding an option to `bash RUN-BLACKSWARM.sh`.

| Option | Purpose |
|---|---|
| `--color always` | Force rainbow ANSI colors |
| `--color auto` / `--color never` | Detect or disable ANSI colors |
| `--color-test` | Show a read-only rainbow test |
| `--examples` | Open the terminal Example Desk |
| `--constellation 1` | Show Constellation for Session ID 1 |
| `--compare 1 2` | Compare saved sessions 1 and 2 |
| `--navigate 1` | Navigate saved Session ID 1 |
| `--bookmarks` | Open Bookmarked Intel directly |
| `--collections` | Open Collections directly |
| `--vault-guard` | Open Vault Guard directly |
| `--demo` | Run one illustrative offline demo |
| `--cli --query "public cybersecurity research" --limit 100` | Run a one-off public-index query and exit |
| `--dashboard` | Start localhost dashboard without opening the browser |
| `--open-dashboard` | Explicitly open the localhost dashboard in the browser |
| `--sources wikipedia,crossref` | Choose sources for a one-off search |
| `--quality focused` / `--quality broad` | Select a relevance-saving mode |
| `--searxng https://example.org` | Supply an authorized HTTPS SearXNG endpoint; replace example URL with an actual permitted instance |

**Tip:** `--query`, `--limit`, `--sources`, `--quality`, and `--searxng` apply to one-off CLI searches; interactive menu [1] asks for these choices instead.

## 🗃️ Data model and privacy

- **Research sessions:** indexed results, ranking, candidates, and Session IDs.
- **Favorites:** independently saved bookmarks and editable notes.
- **Collections:** selected bookmark snapshots grouped into named folders.
- **Tags:** URL-linked labels stored separately.
- **Exports:** written only on explicit request.
- **Backups:** new, unencrypted ZIP snapshots produced only after explicit confirmation.

An item can have a **Session ID**, **Bookmark ID**, **Collection ID**, and **collection Item ID**. These are **different numbers**. Use the number requested by the current terminal prompt.

No private databases, account credentials, personal usernames, hostnames, session histories, or private backups are supplied with the public source repository. **Never publish them.**

## Troubleshooting

- **No results / fewer than requested:** public indexes may have limited or unrelated metadata; change your research query or sources. A limit of 1,000 is a *cap*, not a guarantee.
- **Source timeout:** one index may be temporarily unavailable; inspect terminal source statuses and try another source.
- **No saved sessions:** start a live search with [1], or use [2] to learn from illustrative data.
- **Wrong ID:** check [3] for Session IDs, [12] for Bookmark IDs, and [13] for Collection IDs.
- **Bookmark note accidentally contains `f 1`:** [12] → [3] edits that note.
- **No tagged links:** add a saved favorite to a collection, then [13] → [9] → [2] to tag it.
- **No browser popped up:** this is intentional. BLACKSWARM is terminal-first.
- **Backup verification fails:** treat the backup as untrusted; do not assume the saved archive can be recovered.
- **Colors missing:** run with `--color always`, or test via `--color-test`.

## Public research boundaries

Use BLACKSWARM only for lawful, authorized, passive research of public sources. This application does **not** provide unauthorized intrusion, credential collection, exploit workflows, or private-system scanning. Source links and metadata are untrusted until independently checked.

---

**BLACKSWARM // SCAN · COLLECT · RANK · VISUALIZE · BOOKMARK · ORGANIZE**  
*GlitchByte Phantom Labs · Skull Swarm Edition* ☣️🌈💚💜
