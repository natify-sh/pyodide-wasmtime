"""Pyodide's package lock for micropip, with no JavaScript (guest side).

Outside the browser micropip's compatibility layer has an empty lock and a `loadPackage` that does nothing, so
`micropip.install("numpy")` (a package of Pyodide's own lock, not on PyPI) finds nothing. `hook` (called from
sitecustomize) waits for `micropip._compat` to be imported and then `patch`es its layer: the lock's packages,
info and base URL, and a `loadPackage` that does what Pyodide's JavaScript does for a package of the lock:
the dependencies from `depends`, the wheel from the base URL, its sha256 checked, unpacked into site-packages.
"""

import sys


def patch(compat, lock, base_url):
    layer = compat.compatibility_layer
    layer.lockfile_packages.update(lock["packages"])
    layer.lockfile_info.update(lock["info"])
    layer.lockfile_base_url = compat.lockfile_base_url = base_url

    async def loadPackage(names):
        import hashlib
        import site

        packages, todo, order = layer.lockfile_packages, [names] if isinstance(names, str) else list(names), []
        while todo:  # the closure over `depends`, dependencies first
            name = todo.pop().lower().replace("_", "-")
            if name not in packages:
                raise ValueError(f"No known package with name {name!r}")
            if name not in order:
                order.insert(0, name)
                todo.extend(packages[name]["depends"])
        for name in order:
            pkg = packages[name]
            if pkg["package_type"] != "package":  # shared libraries and cpython modules need the JavaScript loader
                raise NotImplementedError(f"{name}: package_type {pkg['package_type']!r} is not supported")
            if name in layer.loadedPackages.to_py():
                continue
            url = base_url + pkg["file_name"]
            data = await layer.fetch_bytes(url, {})
            if hashlib.sha256(data).hexdigest() != pkg["sha256"]:
                raise RuntimeError(f"Invalid checksum for {url}")
            meta = {
                "PYODIDE_SOURCE": "pyodide",
                "PYODIDE_URL": url,
                "PYODIDE_SHA256": pkg["sha256"],
                "INSTALLER": "pyodide.loadPackage",
            }
            await layer.install(data, pkg["file_name"], site.getsitepackages()[0], meta)
            setattr(layer.loadedPackages, name, "default channel")

    layer.loadPackage = compat.loadPackage = staticmethod(loadPackage)


class _Hook:
    def __init__(self, lock_path, base_url):
        self.lock_path, self.base_url = lock_path, base_url

    def find_spec(self, name, path=None, target=None):
        if name != "micropip._compat":
            return None
        import importlib.util

        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(name)
        loader, exec_module = spec.loader, spec.loader.exec_module

        def run(module):
            import json

            exec_module(module)
            with open(self.lock_path) as f:
                patch(module, json.load(f), self.base_url)

        loader.exec_module = run
        return spec


def hook(lock_path, base_url):
    sys.meta_path.insert(0, _Hook(lock_path, base_url))
