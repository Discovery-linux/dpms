import os

from typing import Dict, Any, Optional, List
if __package__ is None:
    from dpms_frontend import print_error
else:
    from .dpms_frontend import print_error

INDEX_FILE = "packages.txt"
REQUIRED = ['name', 'version', 'source_url', 'dependencies', 'build_steps']


class PackageReader:
    def __init__(self, mirror_path: str):
        self.mirror_path = mirror_path
        self.index = os.path.join(mirror_path, INDEX_FILE)

    def _load(self) -> Optional[List[Dict[str, Any]]]:
        if not os.path.exists(self.index):
            print_error("Missing index", f"Index not found: {self.index}")
            return None

        pkgs = []
        try:
            with open(self.index, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    fields = [f.strip() for f in line.split(',')]
                    if len(fields) != len(REQUIRED):
                        print_error("Parse error", f"Expected {len(REQUIRED)} fields, got {len(fields)}: {line}")
                        continue
                    data = dict(zip(REQUIRED, fields))
                    deps = {}
                    for d in data.pop('dependencies').split('|'):
                        d = d.strip()
                        if d:
                            deps[d] = 'latest'
                    data['dependencies'] = deps
                    pkgs.append(data)
            return pkgs
        except Exception as e:
            print_error("Read failure", f"Failed to read index: {e}")
            return None

    def get_all_packages(self) -> Optional[List[Dict[str, Any]]]:
        return self._load()
