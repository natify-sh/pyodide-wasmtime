"""Pyodide's package lock for micropip, with no JavaScript (guest side).

Outside the browser micropip's compatibility layer has an empty lock and a `loadPackage` that does nothing, so
`micropip.install("numpy")` (a package of Pyodide's own lock, not on PyPI) finds nothing. `hook` (called by the
`pyodide_nojs_start` module that `pyodide_nojs.pth` runs) waits for `micropip._compat` to be imported and then `patch`es its layer: the lock's packages,
info and base URL, and a `loadPackage` that does what Pyodide's JavaScript does for a package of the lock:
the dependencies from `depends`, the wheel from the base URL, its sha256 checked, unpacked into site-packages.
"""

import sys


def patch(compat, lock, base_url):
    layer = compat.compatibility_layer
    layer.lockfile_packages.update(lock["packages"])
    layer.lockfile_info.update(lock["info"])
    layer.lockfile_base_url = compat.lockfile_base_url = base_url

    if "_lock_done" not in layer.__dict__:
        layer._lock_done = set()  # what loadPackage installed, so a later call does not repeat it
    done = layer._lock_done

    def closure(names):  # post-order depth-first: the dependencies of a package come before it; a cycle ends
        packages, order, seen = layer.lockfile_packages, [], set()

        def visit(name):
            name = name.lower().replace("_", "-")
            if name not in packages:
                raise ValueError(f"No known package with name {name!r}")
            if name not in seen:
                seen.add(name)
                for dep in packages[name]["depends"]:
                    visit(dep)
                order.append(name)

        for name in [names] if isinstance(names, str) else names:
            visit(name)
        return order

    async def loadPackage(names):
        import hashlib
        import importlib.metadata
        import site

        packages = layer.lockfile_packages
        for name in closure(names):
            pkg = packages[name]
            if pkg["package_type"] != "package":  # shared libraries and cpython modules need the JavaScript loader
                raise NotImplementedError(f"{name}: package_type {pkg['package_type']!r} is not supported")
            if name in done:
                continue
            try:
                importlib.metadata.distribution(name)
                continue  # already in the guest, from wherever: not overwritten (and numpy is not unpacked over itself)
            except importlib.metadata.PackageNotFoundError:
                pass
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
            done.add(name)

    layer.loadPackage = compat.loadPackage = staticmethod(loadPackage)


class _Loader:
    """The real loader, and `patch` after its exec_module (the original loader object is not touched: a zipimporter is shared)."""

    def __init__(self, loader, after):
        self._loader, self._after = loader, after

    def create_module(self, spec):
        return self._loader.create_module(spec)

    def exec_module(self, module):
        self._loader.exec_module(module)
        self._after(module)

    def __getattr__(self, name):
        return getattr(self._loader, name)


class _Hook:
    def __init__(self, lock_path, base_url):
        self.lock_path, self.base_url = lock_path, base_url

    def find_spec(self, name, path=None, target=None):
        if name != "micropip._compat":
            return None
        from importlib.machinery import PathFinder

        spec = PathFinder.find_spec(name, path)
        if spec is not None:
            spec.loader = _Loader(spec.loader, self._patch)
        return spec

    def _patch(self, module):
        import json

        with open(self.lock_path) as f:
            patch(module, json.load(f), self.base_url)
        sys.meta_path.remove(self)  # only after a success: a failed import fails again the next time


def hook(lock_path, base_url):
    sys.meta_path.insert(0, _Hook(lock_path, base_url))
