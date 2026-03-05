# Adding a Custom Game

If a game is not in the list of supported games, it may be possible to add it as a custom game. Custom games are saved as a `.json` file in Amethyst's config folder and can be shared with others.

To add a custom game, click the **+** button in the top-left corner, then click **Define Custom Game** in the bottom-left of the Add Game window.

<img width="180" height="35" alt="Define Custom Game button" src="https://github.com/user-attachments/assets/d316cfb1-2b42-4491-a573-406ada9a83ff" />

Most properties used by officially supported games can be configured here. The only limitation is that custom deployment logic cannot be defined, as that would require scripting.

---

## Options

### Game Name

The name that will appear for the game in the manager.

---

### Executable Filename

The path to the game's launch executable, relative to the game's root folder.

- Most games have their executable in the root folder — e.g. `SkyrimSELauncher.exe`
- Some games have it in a subfolder — e.g. Baldur's Gate 3 uses `bin/bg3.exe`

---

### Deploy Method

Controls how mod files are placed into the game directory. There are three options:

| Method | Description |
|--------|-------------|
| **Standard** | Mods are deployed into a single target folder (set via **Mod Sub Folder**). Use this for games like Skyrim where all mod files go into `Data`. |
| **Root** | Mods can be deployed into multiple folders within the game's root directory. Use this for games like Cyberpunk 2077, where mods can go into `bin`, `r6`, `archive`, `red4ext`, or `engine`. |
| **UE5** | For Unreal Engine 5 games. Uses custom rules to automatically route each file to the correct location, including `.utoc` files. |

---

### Mod Sub Folder

The folder, relative to the game's root, where mods should be deployed. This does not apply to the **Root** deploy method.

- Skyrim: `Data`
- Subnautica: `BepInEx/Plugins`
- Hogwarts Legacy (UE5): `Phoenix`

---

### Steam App ID

Used to detect the Proton prefix and enable the Proton Tools window for Steam-installed games. The App ID can be found on [steamdb.info](https://steamdb.info).

---

### Nexus Mods Domain

The game's identifier on Nexus Mods. This is visible in the URL when viewing the game's page on Nexus — e.g. `skyrimspecialedition`.

---

### Banner Image

The image displayed in the Add Game interface. Game banners and icons can be found on [SteamGridDB](https://www.steamgriddb.com).

---

## Advanced Options

These options control how a mod's internal folder structure is handled during installation.

For example: if a Skyrim mod is packaged with a `Data` folder included, placing it directly into Skyrim's `Data` folder would cause it to break. The advanced options allow Amethyst to automatically strip or remap these folders so mods install correctly without manual intervention.


