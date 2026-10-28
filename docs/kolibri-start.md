# kolibri-start.sh: the Kolibri App entrypoint

`compose.yaml` runs every Kolibri image through `kolibri-start.sh`, with `entrypoint: ["sh", "/idea/kolibri-start.sh"]` and `command: ["start", "--foreground"]`. The same compose works for `koenswings/kolibri:1.0-0.15.5-dev` and for the official `learningequality/kolibri:0.19.5`, on the same data directory (app-kolibri#13, agent-app-dev#23).

## What the official 0.19.5 `/entrypoint.sh` does, and what we keep

| Official entrypoint / image | kolibri-start.sh |
|---|---|
| Image ENV `KOLIBRI_HOME=/kolibri`; the script also defaults it to `/kolibri` if unset | **Changed.** Compose sets `KOLIBRI_HOME=/root/.kolibri`, so existing 0.15.5 data stays at `./data/kolibri` → `/root/.kolibri`. The script defaults to `/root/.kolibri`. |
| Exits if `KOLIBRI_HOME` is not a mount point | **Kept** (exit 78). It is skipped only if `mountpoint` is missing, or if `KOLIBRI_START_NO_MOUNT_CHECK` is set for tests. |
| Generates a random UUID in `$KOLIBRI_HOME/.node_id` on first run and exports it as `MORANGO_SYSTEM_ID` and `MORANGO_NODE_ID` | **Dropped.** This is why instance_id changed on update and our `MORANGO_SYSTEM_ID=idea-<engine>-<port>` was ignored. The compose value now reaches Kolibri. `MORANGO_NODE_ID` stays unset, as on 0.15.5, so the instance_id does not change on update. An existing `.node_id` file is ignored. |
| When running as root in the user namespace: `chown` every file under `KOLIBRI_HOME` to `kolibri:kolibri`, then `setpriv` to the `kolibri` user | **Dropped.** Kolibri runs as root, as in the 0.15.5 image. Existing kit data is owned by root, and `/root` is not readable by the `kolibri` user. Re-owning field data on update is a separate decision. |
| Image ENV `KOLIBRI_HTTP_PORT=8080`, `KOLIBRI_ZIP_CONTENT_PORT=8081` | Compose sets both: `${port}` and `${port_zip}`. The script **refuses to start** if the zip port is empty, and never falls back to 8081. |
| Image ENV `KOLIBRI_VERSION=0.19.5` | Used as the image version when `KOLIBRI_IMAGE_VERSION` is not set. |
| Provisioning or first-run setup | None in the official entrypoint. Kolibri's own first start does it, unchanged. |
| `exec "$@"` (CMD `kolibri start --foreground`) | `exec <binary> "$@"`. The binary is `$KOLIBRI_BIN`, else `kolibri` on PATH, else `./kolibri-*` in the workdir. |

## job_storage on update

Kolibri 0.15.5 → 0.19.5 with the old `job_storage.sqlite3` crash-loops. The script renames it (and its `-wal`/`-shm`) to `<file>.pre-<dataver>-<UTC stamp>`, never deletes it, and only does so when the data version (`.data_version`) is **older** than the image version. Versions are parsed numerically from any text, so `kolibri, version 0.19.5` and `kolibri-0.15.5, version 0.15.5` work. The image version comes from `KOLIBRI_IMAGE_VERSION`, then `KOLIBRI_VERSION`, then `<binary> --version`. If either version can't be read, nothing moves, and the script logs why.

## Zip-content port (depends on an Engine change)

Kolibri opens a second port, `KOLIBRI_ZIP_CONTENT_PORT`. With `network_mode: host`, two Kolibris on one Engine (for example the real one and the Demo) collide on the default 8081. Engine ports are random in 49152–65534, so `port+N` may belong to another, stopped instance. For that reason we do not derive the zip port from the main port. Compose reads `${port_zip}`, which the Engine will write to the instance `.env` if Steve approves the proposed second-port allocation (Axle). Until then the new compose refuses to start, rather than risk a collision.

## Restart policy

`restart: unless-stopped`. In #23, Kolibri exited with code 0 on a fatal start error, which `on-failure` never restarts. The Engine stops apps with `docker stop`, falling back to `kill`, through the Docker API. A stopped container stays stopped, also after a Docker daemon restart or a reboot.
