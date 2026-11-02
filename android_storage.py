"""Android Storage Access Framework bridge for Nova IDE.

Stages 1-5:
- Launch Android's folder picker (ACTION_OPEN_DOCUMENT_TREE).
- Request read/write access and persist the URI grant.
- Store the selected tree URI and its display name in app-private storage.
- Verify that the persisted grant still exists after app restarts.
- Recursively import the selected document tree into a private local project
  directory so Python code can use ordinary filesystem paths.

Stage 5 synchronizes new and modified local project files back to the
selected SAF folder. Source-side deletions are opt-in to avoid accidental loss.
"""

import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
from urllib.parse import unquote


class StorageBridgeError(RuntimeError):
    """Raised when Android folder access cannot be started or retained."""


class AndroidStorageBridge:
    REQUEST_CODE = 0x4E56  # "NV"; kept separate from ordinary Kivy file results.
    RECORD_FILENAME = "project_folder.json"

    def __init__(self, app_data_dir, platform_name=None,
                 on_folder_selected=None, on_error=None):
        self.app_data_dir = os.path.abspath(app_data_dir)
        self.record_path = os.path.join(self.app_data_dir, self.RECORD_FILENAME)
        self.platform_name = (platform_name or self._detect_platform()).lower()
        self.on_folder_selected = on_folder_selected
        self.on_error = on_error

        self._android_activity_module = None
        self._activity = None
        self._resolver = None
        self._Intent = None
        self._DocumentsContract = None
        self._activity_result_handler = self._on_activity_result
        self._bound = False
        self._pending = False
        self._selection = self._read_record()

    @staticmethod
    def _detect_platform():
        try:
            from kivy.utils import platform
            return platform
        except Exception:
            return "android" if "ANDROID_ARGUMENT" in os.environ else sys.platform

    @property
    def is_android(self):
        return self.platform_name == "android"

    def get_saved_folder(self):
        """Return saved folder metadata, or None when no folder was chosen."""
        if self._selection is None:
            self._selection = self._read_record()
        return dict(self._selection) if self._selection else None

    def _read_record(self):
        try:
            with open(self.record_path, "r", encoding="utf-8") as handle:
                record = json.load(handle)
            uri = record.get("uri")
            name = record.get("name")
            if (isinstance(uri, str) and uri.startswith("content://")
                    and isinstance(name, str) and name.strip()):
                return {"uri": uri, "name": name, "read": bool(record.get("read", True)),
                        "write": bool(record.get("write", True))}
        except (OSError, ValueError, TypeError):
            pass
        return None

    def _write_record(self, record):
        os.makedirs(self.app_data_dir, exist_ok=True)
        temp_path = self.record_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
        os.replace(temp_path, self.record_path)

    def _load_android_api(self):
        if not self.is_android:
            raise StorageBridgeError(
                "Project-folder selection is available in the Android app."
            )
        if self._activity is not None:
            return

        try:
            from android import activity as android_activity
            from jnius import autoclass

            python_activity = autoclass("org.kivy.android.PythonActivity")
            self._activity = python_activity.mActivity
            self._resolver = self._activity.getContentResolver()
            self._Intent = autoclass("android.content.Intent")
            self._DocumentsContract = autoclass("android.provider.DocumentsContract")
            self._android_activity_module = android_activity
        except Exception as exc:
            raise StorageBridgeError(
                "Could not initialize Android's folder picker: %s" % exc
            ) from exc

    def _bind_activity_result(self):
        if self._bound:
            return
        try:
            self._android_activity_module.bind(
                on_activity_result=self._activity_result_handler
            )
            self._bound = True
        except Exception as exc:
            raise StorageBridgeError(
                "Could not listen for the folder-picker result: %s" % exc
            ) from exc

    def select_project_folder(self):
        """Open Android's system folder picker.

        The selected URI and persistable read/write grant are saved after the
        system returns a successful result. The method returns True when the
        picker was launched.
        """
        self._load_android_api()
        if self._pending:
            raise StorageBridgeError("The folder picker is already open.")
        self._bind_activity_result()

        intent = self._Intent(self._Intent.ACTION_OPEN_DOCUMENT_TREE)
        grant_flags = (
            self._Intent.FLAG_GRANT_READ_URI_PERMISSION
            | self._Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            | self._Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
            | self._Intent.FLAG_GRANT_PREFIX_URI_PERMISSION
        )
        intent.addFlags(grant_flags)

        try:
            self._pending = True
            self._activity.startActivityForResult(intent, self.REQUEST_CODE)
        except Exception as exc:
            self._pending = False
            raise StorageBridgeError(
                "Android could not open the folder picker: %s" % exc
            ) from exc
        return True

    def _folder_display_name(self, tree_uri):
        """Get the folder name from DocumentsProvider metadata when possible."""
        try:
            document_id = self._DocumentsContract.getTreeDocumentId(tree_uri)
            document_uri = self._DocumentsContract.buildDocumentUriUsingTree(
                tree_uri, document_id
            )
            cursor = self._resolver.query(document_uri, None, None, None, None)
            if cursor is not None:
                try:
                    if cursor.moveToFirst():
                        column = cursor.getColumnIndex("_display_name")
                        if column >= 0:
                            name = cursor.getString(column)
                            if name:
                                return str(name)
                finally:
                    cursor.close()

            # Common external-storage document IDs look like
            # "primary:Documents/MyGame".
            text = str(document_id).split(":", 1)[-1].rstrip("/")
            if text:
                return unquote(text.rsplit("/", 1)[-1])
        except Exception:
            pass

        try:
            tail = tree_uri.getLastPathSegment()
            if tail:
                return unquote(str(tail))
        except Exception:
            pass
        return "Selected project folder"

    def _on_activity_result(self, request_code, result_code, intent):
        if int(request_code) != self.REQUEST_CODE:
            return
        self._pending = False

        # Android returns RESULT_CANCELED when the user backs out. That is not
        # an error and should not replace a previously selected folder.
        if int(result_code) != -1 or intent is None:
            return

        try:
            tree_uri = intent.getData()
            if tree_uri is None:
                raise StorageBridgeError("Android returned an empty folder URI.")

            read_flag = self._Intent.FLAG_GRANT_READ_URI_PERMISSION
            write_flag = self._Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            persist_flag = self._Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
            result_flags = int(intent.getFlags())
            granted_flags = result_flags & (read_flag | write_flag)
            if (granted_flags & read_flag) == 0 or (granted_flags & write_flag) == 0:
                raise StorageBridgeError(
                    "Android did not grant both read and write access. "
                    "Please choose the project folder again."
                )
            if (result_flags & persist_flag) == 0:
                raise StorageBridgeError(
                    "This storage provider did not offer persistent folder access. "
                    "Please choose a folder from the Android system file picker."
                )

            # Persist only the read/write bits returned by the system picker.
            self._resolver.takePersistableUriPermission(tree_uri, granted_flags)

            record = {
                "uri": str(tree_uri.toString()),
                "name": self._folder_display_name(tree_uri),
                "read": True,
                "write": True,
            }
            self._write_record(record)
            self._selection = record

            if self.on_folder_selected is not None:
                self.on_folder_selected(dict(record))
        except Exception as exc:
            self._notify_error(str(exc))

    def has_persisted_permission(self, record=None):
        """Return True only when Android still holds read and write grants."""
        record = record or self.get_saved_folder()
        if not record or not self.is_android:
            return False
        try:
            self._load_android_api()
            permissions = self._resolver.getPersistedUriPermissions()
            expected_uri = record.get("uri")
            for index in range(permissions.size()):
                permission = permissions.get(index)
                uri = permission.getUri()
                if uri is None or str(uri.toString()) != expected_uri:
                    continue
                return bool(permission.isReadPermission() and permission.isWritePermission())
        except Exception:
            return False
        return False

    def project_cache_path(self, projects_dir=None, record=None):
        """Return a stable private directory for the selected SAF folder."""
        record = record or self.get_saved_folder()
        if not record or not record.get("uri"):
            raise StorageBridgeError("Choose a project folder first.")
        projects_dir = os.path.abspath(
            projects_dir or os.path.join(self.app_data_dir, "projects")
        )
        name = str(record.get("name") or "project").strip()
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-") or "project"
        name = name[:48]
        digest = hashlib.sha256(record["uri"].encode("utf-8")).hexdigest()[:16]
        return os.path.join(projects_dir, "%s-%s" % (name, digest))

    @staticmethod
    def _safe_document_name(name):
        """Reject path separators and traversal names from provider metadata."""
        name = str(name or "").strip()
        if (not name or name in (".", "..") or "/" in name or "\\" in name
                or "\x00" in name or os.path.isabs(name)):
            raise StorageBridgeError(
                "The selected folder contains a file with an unsafe name."
            )
        return name

    @staticmethod
    def _remove_local_path(path):
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def _query_children(self, tree_uri, parent_document_id):
        """Return child rows while ensuring the Android Cursor is closed."""
        from jnius import jarray

        children_uri = self._DocumentsContract.buildChildDocumentsUriUsingTree(
            tree_uri, parent_document_id
        )
        projection = jarray("java.lang.String")([
            "document_id", "_display_name", "mime_type"
        ])
        cursor = self._resolver.query(children_uri, projection, None, None, None)
        if cursor is None:
            return []
        rows = []
        try:
            id_col = cursor.getColumnIndex("document_id")
            name_col = cursor.getColumnIndex("_display_name")
            mime_col = cursor.getColumnIndex("mime_type")
            if id_col < 0 or name_col < 0 or mime_col < 0:
                raise StorageBridgeError(
                    "The selected storage provider returned incomplete file metadata."
                )
            while cursor.moveToNext():
                document_id = cursor.getString(id_col)
                display_name = cursor.getString(name_col)
                mime_type = cursor.getString(mime_col)
                if document_id is None or display_name is None:
                    continue
                rows.append((str(document_id), str(display_name),
                             str(mime_type or "")))
        finally:
            cursor.close()
        return rows

    def _copy_input_stream(self, stream, destination, stats, progress_callback):
        """Copy an Android InputStream to a local file in bounded chunks."""
        from jnius import jarray

        buffer = jarray("b")([0] * (64 * 1024))
        try:
            with open(destination, "wb") as output:
                while True:
                    count = int(stream.read(buffer))
                    if count < 0:
                        break
                    if count == 0:
                        # Defensive fallback for non-standard providers that
                        # return zero for a non-empty read buffer.
                        single = int(stream.read())
                        if single < 0:
                            break
                        output.write(bytes((single & 0xff,)))
                        stats["bytes"] += 1
                        continue
                    output.write(bytes((int(buffer[i]) & 0xff
                                        for i in range(count))))
                    stats["bytes"] += count
            stats["files"] += 1
            if progress_callback is not None:
                try:
                    progress_callback(stats["files"], stats["bytes"])
                except Exception:
                    pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _copy_document_directory(self, tree_uri, document_id, local_dir,
                                 stats, seen_ids, progress_callback, depth=0):
        if depth > 80:
            raise StorageBridgeError(
                "The project folder has too many nested directory levels."
            )
        if document_id in seen_ids:
            return
        seen_ids.add(document_id)
        os.makedirs(local_dir, exist_ok=True)

        for child_id, display_name, mime_type in self._query_children(
                tree_uri, document_id):
            safe_name = self._safe_document_name(display_name)
            child_path = os.path.join(local_dir, safe_name)
            # The validation above forbids separators, but keep this guard so
            # changes to filename handling cannot accidentally escape the root.
            if os.path.commonpath((os.path.abspath(local_dir),
                                   os.path.abspath(child_path))) != os.path.abspath(local_dir):
                raise StorageBridgeError("A project item resolved outside its folder.")

            if mime_type == "vnd.android.document/directory":
                stats["folders"] += 1
                self._copy_document_directory(
                    tree_uri, child_id, child_path, stats, seen_ids,
                    progress_callback, depth + 1
                )
                continue

            document_uri = self._DocumentsContract.buildDocumentUriUsingTree(
                tree_uri, child_id
            )
            stream = self._resolver.openInputStream(document_uri)
            if stream is None:
                raise StorageBridgeError(
                    "Could not read project file: %s" % display_name
                )
            self._copy_input_stream(stream, child_path, stats, progress_callback)

    def import_project(self, destination=None, record=None, progress_callback=None):
        """Copy the selected SAF folder into an app-private local directory.

        The import is staged next to the destination and swapped into place only
        after the full tree has been copied. If the copy fails, the previous
        local project copy is kept intact.

        Returns a dictionary with files, folders, and bytes counters.
        """
        record = record or self.get_saved_folder()
        if not record:
            raise StorageBridgeError("Choose a project folder before importing.")
        if not self.is_android:
            raise StorageBridgeError(
                "Project import is available when the IDE runs on Android."
            )
        if not self.has_persisted_permission(record):
            raise StorageBridgeError(
                "The project-folder permission is no longer available. "
                "Choose the folder again in the Android picker."
            )

        self._load_android_api()
        destination = os.path.abspath(
            destination or self.project_cache_path(record=record)
        )
        parent = os.path.dirname(destination)
        os.makedirs(parent, exist_ok=True)
        staging = destination + ".importing"
        backup = destination + ".previous"
        self._remove_local_path(staging)
        # Recover a valid prior import if the app was interrupted between the
        # directory swap steps during an earlier import.
        if not os.path.exists(destination) and os.path.exists(backup):
            os.replace(backup, destination)
        else:
            self._remove_local_path(backup)

        from jnius import autoclass
        uri_class = autoclass("android.net.Uri")
        tree_uri = uri_class.parse(record["uri"])
        moved_old = False
        try:
            root_document_id = str(
                self._DocumentsContract.getTreeDocumentId(tree_uri)
            )
            stats = {"files": 0, "folders": 0, "bytes": 0}
            self._copy_document_directory(
                tree_uri, root_document_id, staging, stats, set(),
                progress_callback
            )

            if os.path.exists(destination):
                os.replace(destination, backup)
                moved_old = True
            try:
                os.replace(staging, destination)
            except Exception:
                if moved_old and os.path.exists(backup):
                    os.replace(backup, destination)
                    moved_old = False
                raise
            if moved_old:
                self._remove_local_path(backup)
                moved_old = False
            return stats
        except Exception as exc:
            self._remove_local_path(staging)
            # Never delete the only remaining copy if replacing the directory
            # failed. Restore the previous import whenever it is still present.
            if moved_old and os.path.exists(backup) and not os.path.exists(destination):
                try:
                    os.replace(backup, destination)
                    moved_old = False
                except Exception:
                    pass
            if not moved_old:
                self._remove_local_path(backup)
            if isinstance(exc, StorageBridgeError):
                raise
            raise StorageBridgeError("Could not import project folder: %s" % exc) from exc


    @staticmethod
    def _relative_parts(relative_path):
        """Validate and split a normalized project-relative path."""
        if not isinstance(relative_path, str) or not relative_path or relative_path.startswith("/"):
            raise StorageBridgeError("A project item has an invalid relative path.")
        parts = relative_path.split("/")
        return [AndroidStorageBridge._safe_document_name(part) for part in parts]

    def _scan_local_project(self, root):
        """Return project-relative file and directory maps without following symlinks."""
        root = os.path.realpath(os.path.abspath(root))
        if not os.path.isdir(root):
            raise StorageBridgeError("The local project folder no longer exists.")

        files = {}
        directories = set()
        for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            # Python bytecode is generated by imports and should not be copied
            # back into a source project. Symlinks are deliberately not followed.
            kept_dirs = []
            for dirname in dirnames:
                full = os.path.join(current, dirname)
                if os.path.islink(full):
                    continue
                if dirname == "__pycache__":
                    continue
                kept_dirs.append(dirname)
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                self._relative_parts(rel)
                directories.add(rel)
            dirnames[:] = kept_dirs

            for filename in filenames:
                full = os.path.join(current, filename)
                if os.path.islink(full) or filename.endswith((".pyc", ".pyo")):
                    continue
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                self._relative_parts(rel)
                if not os.path.isfile(full):
                    continue
                files[rel] = full
        return files, directories

    def _scan_remote_project(self, tree_uri, root_document_id):
        """Index existing SAF documents by their project-relative paths."""
        files = {}
        directories = {"": {"document_id": str(root_document_id)}}
        seen_ids = set()

        def visit(parent_id, parent_path, depth):
            if depth > 80:
                raise StorageBridgeError(
                    "The selected storage folder has too many nested directory levels."
                )
            if parent_id in seen_ids:
                return
            seen_ids.add(parent_id)

            for child_id, display_name, mime_type in self._query_children(
                    tree_uri, parent_id):
                name = self._safe_document_name(display_name)
                relative = (parent_path + "/" + name).strip("/")
                if relative in files or relative in directories:
                    raise StorageBridgeError(
                        "The storage provider returned duplicate project paths: %s" % relative
                    )
                if mime_type == "vnd.android.document/directory":
                    directories[relative] = {"document_id": child_id}
                    visit(child_id, relative, depth + 1)
                else:
                    files[relative] = {
                        "document_id": child_id,
                        "mime_type": mime_type or "application/octet-stream",
                    }

        visit(str(root_document_id), "", 0)
        return files, directories

    @staticmethod
    def _hash_local_file(path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(64 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.digest()

    def _hash_remote_document(self, tree_uri, document_id):
        """Hash a remote file in bounded chunks, closing its InputStream."""
        from jnius import jarray

        document_uri = self._DocumentsContract.buildDocumentUriUsingTree(
            tree_uri, document_id
        )
        stream = self._resolver.openInputStream(document_uri)
        if stream is None:
            raise StorageBridgeError("Could not read a file in the selected storage folder.")
        digest = hashlib.sha256()
        buffer = jarray("b")([0] * (64 * 1024))
        try:
            while True:
                count = int(stream.read(buffer))
                if count < 0:
                    break
                if count == 0:
                    single = int(stream.read())
                    if single < 0:
                        break
                    digest.update(bytes((single & 0xff,)))
                else:
                    digest.update(bytes((int(buffer[i]) & 0xff for i in range(count))))
        finally:
            try:
                stream.close()
            except Exception:
                pass
        return digest.digest()

    def _write_local_file_to_document(self, local_path, document_uri,
                                      new_document=False):
        """Stream a local file to SAF, requesting truncation for existing files.

        Android providers may interpret mode ``w`` without truncating. Existing
        documents therefore require ``wt`` or ``rwt``; plain ``w`` is used only
        for a brand-new, empty document when a provider rejects truncate modes.
        """
        from jnius import jarray

        output = None
        modes = ("wt", "rwt", "w") if new_document else ("wt", "rwt")
        last_error = None
        for mode in modes:
            try:
                output = self._resolver.openOutputStream(document_uri, mode)
                if output is not None:
                    break
            except Exception as exc:
                last_error = exc
        if output is None:
            detail = (": %s" % last_error) if last_error is not None else ""
            raise StorageBridgeError(
                "The selected storage provider could not open a truncating file stream%s." % detail
            )

        write_error = False
        try:
            buffer = jarray("b")([0] * (64 * 1024))
            with open(local_path, "rb") as source:
                while True:
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    for index, value in enumerate(chunk):
                        buffer[index] = value if value < 128 else value - 256
                    output.write(buffer, 0, len(chunk))
            output.flush()
        except Exception:
            write_error = True
            raise
        finally:
            try:
                output.close()
            except Exception:
                if not write_error:
                    raise

    def _create_remote_document(self, tree_uri, parent_id, name, mime_type):
        parent_uri = self._DocumentsContract.buildDocumentUriUsingTree(
            tree_uri, parent_id
        )
        created_uri = self._DocumentsContract.createDocument(
            self._resolver, parent_uri, mime_type, name
        )
        if created_uri is None:
            raise StorageBridgeError("Could not create project item: %s" % name)
        try:
            document_id = str(self._DocumentsContract.getDocumentId(created_uri))
        except Exception as exc:
            raise StorageBridgeError(
                "The storage provider created '%s' but did not return its document ID." % name
            ) from exc
        return created_uri, document_id

    def sync_project(self, source_root, record=None, delete_missing=False,
                     progress_callback=None):
        """Push local project files to the selected SAF folder.

        New and modified files are created or replaced. By default, items that
        exist only in the selected storage folder are preserved. When
        ``delete_missing`` is True, remote files and directories absent from
        the local mirror are deleted after all local writes have succeeded.

        The method is intended to run on a worker thread. It returns counters
        for created, updated, unchanged, deleted, preserved, and transferred
        bytes.
        """
        record = record or self.get_saved_folder()
        if not record:
            raise StorageBridgeError("Choose a project folder before syncing.")
        if not self.is_android:
            raise StorageBridgeError(
                "Project synchronization is available when the IDE runs on Android."
            )
        if not self.has_persisted_permission(record):
            raise StorageBridgeError(
                "The project-folder permission is no longer available. "
                "Choose the folder again in the Android picker."
            )

        source_root = os.path.abspath(source_root)
        local_files, local_dirs = self._scan_local_project(source_root)
        self._load_android_api()

        from jnius import autoclass
        uri_class = autoclass("android.net.Uri")
        tree_uri = uri_class.parse(record["uri"])
        try:
            root_document_id = str(
                self._DocumentsContract.getTreeDocumentId(tree_uri)
            )
            remote_files, remote_dirs = self._scan_remote_project(
                tree_uri, root_document_id
            )
        except Exception as exc:
            if isinstance(exc, StorageBridgeError):
                raise
            raise StorageBridgeError("Could not inspect the selected storage folder: %s" % exc) from exc

        stats = {
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "folders_created": 0,
            "deleted_files": 0,
            "deleted_folders": 0,
            "preserved_remote_only": 0,
            "bytes": 0,
            "processed": 0,
            "total": len(local_files),
        }

        def report(path, action):
            if progress_callback is not None:
                try:
                    progress_callback(
                        stats["processed"], stats["total"], path,
                        action, stats["bytes"]
                    )
                except Exception:
                    pass

        # Create any missing local directories in parent-before-child order.
        for relative in sorted(local_dirs, key=lambda value: (value.count("/"), value)):
            if relative in remote_files:
                raise StorageBridgeError(
                    "A file in the selected folder conflicts with local directory '%s'." % relative
                )
            if relative in remote_dirs:
                continue
            parts = self._relative_parts(relative)
            parent_path = "/".join(parts[:-1])
            parent_entry = remote_dirs.get(parent_path)
            if parent_entry is None:
                raise StorageBridgeError(
                    "Could not find parent folder for project directory '%s'." % relative
                )
            _uri, new_id = self._create_remote_document(
                tree_uri, parent_entry["document_id"], parts[-1],
                "vnd.android.document/directory"
            )
            remote_dirs[relative] = {"document_id": new_id}
            stats["folders_created"] += 1

        # Add or update files. Existing contents are hashed first so unchanged
        # assets do not need to be written again.
        for relative in sorted(local_files):
            parts = self._relative_parts(relative)
            parent_path = "/".join(parts[:-1])
            parent_entry = remote_dirs.get(parent_path)
            if parent_entry is None:
                raise StorageBridgeError(
                    "Could not find destination folder for '%s'." % relative
                )
            if relative in remote_dirs:
                raise StorageBridgeError(
                    "A folder in the selected storage folder conflicts with local file '%s'." % relative
                )

            local_path = local_files[relative]
            local_hash = self._hash_local_file(local_path)
            existing = remote_files.get(relative)
            if existing is not None:
                remote_hash = self._hash_remote_document(
                    tree_uri, existing["document_id"]
                )
                if local_hash == remote_hash:
                    stats["unchanged"] += 1
                    stats["processed"] += 1
                    report(relative, "unchanged")
                    continue
                document_uri = self._DocumentsContract.buildDocumentUriUsingTree(
                    tree_uri, existing["document_id"]
                )
                self._write_local_file_to_document(local_path, document_uri)
                stats["updated"] += 1
                action = "updated"
            else:
                mime_type = mimetypes.guess_type(parts[-1])[0] or "application/octet-stream"
                document_uri, new_id = self._create_remote_document(
                    tree_uri, parent_entry["document_id"], parts[-1], mime_type
                )
                try:
                    self._write_local_file_to_document(
                        local_path, document_uri, new_document=True
                    )
                except Exception:
                    # Remove a newly-created partial file when possible.
                    try:
                        self._DocumentsContract.deleteDocument(self._resolver, document_uri)
                    except Exception:
                        pass
                    raise
                remote_files[relative] = {
                    "document_id": new_id,
                    "mime_type": mime_type,
                }
                stats["created"] += 1
                action = "created"

            file_size = os.path.getsize(local_path)
            stats["bytes"] += file_size
            stats["processed"] += 1
            report(relative, action)

        # Deletions are deliberately opt-in. Without this flag, remote-only
        # items are retained rather than risking removal of files added outside
        # the IDE since the last import.
        if delete_missing:
            stale_files = [
                (relative, entry) for relative, entry in remote_files.items()
                if relative not in local_files
            ]
            for relative, entry in sorted(stale_files, key=lambda item: item[0], reverse=True):
                document_uri = self._DocumentsContract.buildDocumentUriUsingTree(
                    tree_uri, entry["document_id"]
                )
                deleted = self._DocumentsContract.deleteDocument(
                    self._resolver, document_uri
                )
                if deleted is False:
                    raise StorageBridgeError("Could not delete removed file: %s" % relative)
                stats["deleted_files"] += 1

            stale_dirs = [
                (relative, entry) for relative, entry in remote_dirs.items()
                if relative and relative not in local_dirs
            ]
            for relative, entry in sorted(
                    stale_dirs, key=lambda item: (item[0].count("/"), item[0]),
                    reverse=True):
                document_uri = self._DocumentsContract.buildDocumentUriUsingTree(
                    tree_uri, entry["document_id"]
                )
                deleted = self._DocumentsContract.deleteDocument(
                    self._resolver, document_uri
                )
                if deleted is False:
                    raise StorageBridgeError("Could not delete removed folder: %s" % relative)
                stats["deleted_folders"] += 1
        else:
            stats["preserved_remote_only"] = sum(
                1 for relative in remote_files if relative not in local_files
            )

        return stats

    def clear_project_folder(self):
        """Forget the selected folder and release its persisted URI grant."""
        record = self.get_saved_folder()
        if record and self.is_android:
            try:
                self._load_android_api()
                uri_class = __import__("jnius").autoclass("android.net.Uri")
                uri = uri_class.parse(record["uri"])
                flags = (self._Intent.FLAG_GRANT_READ_URI_PERMISSION
                         | self._Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                self._resolver.releasePersistableUriPermission(uri, flags)
            except Exception:
                # Removing the app's saved pointer is still useful even if the
                # provider has already revoked or removed the document tree.
                pass
        try:
            os.remove(self.record_path)
        except FileNotFoundError:
            pass
        self._selection = None

    def unbind(self):
        """Unregister the Android activity-result callback during app shutdown."""
        if not self._bound or self._android_activity_module is None:
            return
        try:
            self._android_activity_module.unbind(
                on_activity_result=self._activity_result_handler
            )
        except Exception:
            pass
        self._bound = False

    def _notify_error(self, message):
        if self.on_error is not None:
            try:
                self.on_error(message)
            except Exception:
                pass
